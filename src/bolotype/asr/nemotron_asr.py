from __future__ import annotations

import queue
import threading
from typing import Callable

import numpy as np

from .base import ASRTranscriber

_SAMPLE_RATE = 16000
_BLOCK_SIZE = 512  # frames per sounddevice callback
_SUPPORTED_LOOKAHEAD_TOKENS = {0, 1, 3, 6, 13}


class NemotronTranscriber(ASRTranscriber):
    def __init__(
        self,
        language: str = "en-US",
        model_id: str = "nvidia/nemotron-3.5-asr-streaming-0.6b",
        lookahead_tokens: int = 3,
        vad_threshold: float = 0.01,
        silence_duration_s: float = 1.25,
    ) -> None:
        if lookahead_tokens not in _SUPPORTED_LOOKAHEAD_TOKENS:
            raise ValueError(
                f"Unsupported lookahead_tokens={lookahead_tokens}. "
                f"Expected one of {sorted(_SUPPORTED_LOOKAHEAD_TOKENS)}."
            )

        self._language = language
        self._model_id = model_id
        self._lookahead_tokens = lookahead_tokens
        self._vad_threshold = vad_threshold
        self._silence_frames = int(silence_duration_s * _SAMPLE_RATE / _BLOCK_SIZE)
        self._listeners: list[Callable[[str], None]] = []

        self._audio_queue: queue.Queue[np.ndarray] = queue.Queue()
        self._transcription_queue: queue.Queue[np.ndarray | None] = queue.Queue()

        self._stream = None
        self._vad_thread: threading.Thread | None = None
        self._transcription_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        print(f"Loading Nemotron model {model_id!r}...")
        from transformers import AutoModelForRNNT, AutoProcessor
        self._processor = AutoProcessor.from_pretrained(model_id)
        self._processor.set_num_lookahead_tokens(lookahead_tokens)
        self._model = AutoModelForRNNT.from_pretrained(model_id, device_map="auto")
        self._model.eval()
        print(
            f"Nemotron ready. "
            f"Lookahead tokens: {lookahead_tokens}; "
            f"streaming latency: {self._processor.streaming_latency_ms} ms; "
            f"first samples: {self._processor.num_samples_first_audio_chunk}; "
            f"next samples: {self._processor.num_samples_per_audio_chunk}"
        )

    def add_listener(self, cb: Callable[[str], None]) -> None:
        self._listeners.append(cb)

    def start(self) -> None:
        if self._stream is not None:
            return

        import sounddevice as sd
        self._stop_event.clear()

        self._transcription_thread = threading.Thread(
            target=self._transcription_worker,
            name="nemotron-transcription",
            daemon=True,
        )
        self._vad_thread = threading.Thread(
            target=self._vad_worker,
            name="nemotron-vad",
            daemon=True,
        )
        self._stream = sd.InputStream(
            samplerate=_SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=_BLOCK_SIZE,
            callback=self._audio_callback,
        )
        self._transcription_thread.start()
        self._stream.start()
        self._vad_thread.start()

    def stop(self) -> None:
        if self._stream is None and self._vad_thread is None:
            return

        self._stop_event.set()

        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        if self._vad_thread is not None:
            self._vad_thread.join(timeout=3)
            self._vad_thread = None

        # Wait for all utterances the VAD worker already submitted.
        self._transcription_queue.join()

        # Send sentinel to stop the transcription worker.
        if self._transcription_thread is not None:
            self._transcription_queue.put(None)
            self._transcription_queue.join()
            self._transcription_thread.join(timeout=5)
            self._transcription_thread = None

    def close(self) -> None:
        self.stop()
        del self._model
        del self._processor
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    # ------------------------------------------------------------------
    # Internal

    def _audio_callback(self, indata, frames, time, status) -> None:  # noqa: ARG002
        if status:
            print(f"[nemotron audio] {status}", flush=True)
        self._audio_queue.put(indata[:, 0].copy())

    def _vad_worker(self) -> None:
        from collections import deque

        speech_chunks: list[np.ndarray] = []
        in_speech = False
        silence_count = 0

        start_threshold = self._vad_threshold
        continue_threshold = self._vad_threshold * 0.6

        pre_roll_blocks = max(1, int(0.25 * _SAMPLE_RATE / _BLOCK_SIZE))
        pre_roll: deque[np.ndarray] = deque(maxlen=pre_roll_blocks)

        try:
            while not self._stop_event.is_set():
                try:
                    chunk = self._audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                try:
                    rms = float(np.sqrt(np.mean(chunk * chunk)))

                    if not in_speech:
                        pre_roll.append(chunk)
                        if rms >= start_threshold:
                            speech_chunks = list(pre_roll)
                            pre_roll.clear()
                            in_speech = True
                            silence_count = 0

                    elif rms >= continue_threshold:
                        speech_chunks.append(chunk)
                        silence_count = 0

                    else:
                        speech_chunks.append(chunk)
                        silence_count += 1
                        if silence_count >= self._silence_frames:
                            audio = np.concatenate(speech_chunks)
                            speech_chunks = []
                            in_speech = False
                            silence_count = 0
                            pre_roll.clear()
                            if audio.size > 0:
                                self._transcription_queue.put(audio)
                finally:
                    self._audio_queue.task_done()
        finally:
            # Flush any speech still buffered when stop() is called.
            if speech_chunks:
                audio = np.concatenate(speech_chunks)
                if audio.size > 0:
                    self._transcription_queue.put(audio)

    def _transcription_worker(self) -> None:
        while True:
            try:
                audio = self._transcription_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                if audio is None:
                    return
                self._transcribe_utterance(audio)
            except Exception as exc:
                import traceback
                print(f"\n[nemotron worker error] {exc}", flush=True)
                traceback.print_exc()
            finally:
                self._transcription_queue.task_done()

    def _transcribe_utterance(self, audio: np.ndarray) -> None:
        from threading import Thread
        from transformers import TextIteratorStreamer

        processor = self._processor
        model = self._model
        language = self._language
        sampling_rate = _SAMPLE_RATE

        try:
            audio = np.asarray(audio, dtype=np.float32).reshape(-1)
            if audio.size == 0:
                return

            first_sample_count = processor.num_samples_first_audio_chunk
            next_sample_count = processor.num_samples_per_audio_chunk
            expected_first_frames = processor.num_mel_frames_first_audio_chunk
            expected_next_frames = processor.num_mel_frames_per_audio_chunk

            first_audio_chunk = audio[:first_sample_count]
            if first_audio_chunk.size < first_sample_count:
                first_audio_chunk = np.pad(
                    first_audio_chunk,
                    (0, first_sample_count - first_audio_chunk.size),
                )

            first_chunk_inputs = processor(
                first_audio_chunk,
                sampling_rate=sampling_rate,
                is_streaming=True,
                is_first_audio_chunk=True,
                language=language,
                return_tensors="pt",
            )
            first_chunk_inputs = first_chunk_inputs.to(model.device, dtype=model.dtype)

            actual_first_frames = first_chunk_inputs.input_features.shape[1]
            if actual_first_frames < expected_first_frames:
                raise RuntimeError(
                    f"Processor produced too few mel frames for first chunk: "
                    f"got {actual_first_frames}, expected {expected_first_frames}. "
                    f"lookahead_tokens={self._lookahead_tokens}, "
                    f"input_samples={first_audio_chunk.size}."
                )

            def _input_features_gen():
                yield first_chunk_inputs.input_features[:, :expected_first_frames, :]

                mel_frame_idx = expected_first_frames
                hop_length = processor.feature_extractor.hop_length
                n_fft = processor.feature_extractor.n_fft
                start_idx = mel_frame_idx * hop_length - n_fft // 2

                while start_idx < audio.shape[0]:
                    audio_chunk = audio[start_idx: start_idx + next_sample_count]
                    if audio_chunk.size < next_sample_count:
                        audio_chunk = np.pad(
                            audio_chunk,
                            (0, next_sample_count - audio_chunk.size),
                        )

                    inputs = processor(
                        audio_chunk,
                        sampling_rate=sampling_rate,
                        is_streaming=True,
                        is_first_audio_chunk=False,
                        language=language,
                        return_tensors="pt",
                    )
                    inputs = inputs.to(model.device, dtype=model.dtype)

                    actual_frames = inputs.input_features.shape[1]
                    if actual_frames < expected_next_frames:
                        raise RuntimeError(
                            f"Processor produced too few mel frames for subsequent chunk: "
                            f"got {actual_frames}, expected {expected_next_frames}. "
                            f"lookahead_tokens={self._lookahead_tokens}, "
                            f"input_samples={audio_chunk.size}."
                        )

                    yield inputs.input_features[:, :expected_next_frames, :]

                    mel_frame_idx += expected_next_frames
                    start_idx = mel_frame_idx * hop_length - n_fft // 2

            streamer = TextIteratorStreamer(processor.tokenizer, skip_special_tokens=True)
            generate_kwargs = dict(first_chunk_inputs)
            generate_kwargs["input_features"] = _input_features_gen()
            generate_kwargs["streamer"] = streamer
            generate_kwargs["max_new_tokens"] = 512

            generate_error: list[BaseException] = []

            def _generate() -> None:
                try:
                    model.generate(**generate_kwargs)
                except BaseException as exc:
                    generate_error.append(exc)
                    streamer.end()

            t = Thread(target=_generate, daemon=True)
            t.start()

            parts: list[str] = []
            for text_chunk in streamer:
                parts.append(text_chunk)
            t.join()

            if generate_error:
                raise generate_error[0]

            text = "".join(parts).strip()
            if text:
                print(f"\n[nemotron] {text!r}", flush=True)
                for cb in self._listeners:
                    cb(text)

        except Exception as exc:
            import traceback
            print(f"\n[nemotron transcribe error] {exc}", flush=True)
            traceback.print_exc()
