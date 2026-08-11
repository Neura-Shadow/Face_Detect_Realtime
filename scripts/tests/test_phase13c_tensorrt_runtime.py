"""Phase 13C TensorRT runtime tests using fakes and CUDA test doubles.

No real engine, GPU or TensorRT installation is required: the engine runner is
exercised through a fake runner and the CUDA wrapper through a ctypes-shaped
test double, which is exactly what Gate A is allowed to assert.
"""

from __future__ import annotations

import ctypes
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workers.core.tensorrt_asset_contract import InputContract, OutputContract, PostprocessProfile
from workers.core.tensorrt_perception import TensorRTPerceptionBackend, TensorRTPerceptionError
from workers.core.tensorrt_runtime import (
    CUDA_MEMCPY_DEVICE_TO_HOST,
    CUDA_MEMCPY_HOST_TO_DEVICE,
    CudaRuntime,
    TensorRTRuntimeError,
    cuda_preflight,
    find_cuda_runtime_library,
    tensorrt_preflight,
    trt_dtype_to_numpy,
)


def _as_int(value: Any) -> int:
    """Unwrap a ctypes scalar the way a real CDLL entry point would.

    A real ``CDLL`` converts ``c_size_t``/``c_int`` arguments back to Python
    ints; this double receives the ctypes objects verbatim, so it has to
    unwrap them itself.
    """

    return int(getattr(value, "value", value))


class FakeCudaLibrary:
    """ctypes-shaped CUDA runtime double that records every call."""

    def __init__(self, *, fail_on: str = "") -> None:
        self.calls = []  # type: List[str]
        self.fail_on = fail_on
        self.allocations = {}  # type: Dict[int, int]
        self.freed = []  # type: List[int]
        self.streams = []  # type: List[int]
        self.destroyed_streams = []  # type: List[int]
        self.events = []  # type: List[int]
        self.destroyed_events = []  # type: List[int]
        self._next_handle = 0x1000
        self._device_memory = {}  # type: Dict[int, bytes]

    def _status(self, name: str) -> int:
        self.calls.append(name)
        return 1 if self.fail_on == name else 0

    def _handle(self) -> int:
        self._next_handle += 0x100
        return self._next_handle

    def cudaMalloc(self, pointer, size):  # noqa: N802 - mirrors the C name
        status = self._status("cudaMalloc")
        if status:
            return status
        handle = self._handle()
        self.allocations[handle] = _as_int(size)
        pointer._obj.value = handle
        return 0

    def cudaFree(self, pointer):  # noqa: N802
        status = self._status("cudaFree")
        if not status:
            self.freed.append(_as_int(pointer) or 0)
        return status

    def cudaMemcpyAsync(self, destination, source, size, kind, stream):  # noqa: N802
        status = self._status("cudaMemcpyAsync")
        if status:
            return status
        length = _as_int(size)
        if _as_int(kind) == CUDA_MEMCPY_HOST_TO_DEVICE:
            self._device_memory[_as_int(destination) or 0] = ctypes.string_at(source, length)
        elif _as_int(kind) == CUDA_MEMCPY_DEVICE_TO_HOST:
            payload = self._device_memory.get(_as_int(source) or 0, b"\x00" * length)
            ctypes.memmove(destination, payload, min(len(payload), length))
        return 0

    def cudaStreamCreate(self, stream):  # noqa: N802
        status = self._status("cudaStreamCreate")
        if status:
            return status
        handle = self._handle()
        self.streams.append(handle)
        stream._obj.value = handle
        return 0

    def cudaStreamDestroy(self, stream):  # noqa: N802
        status = self._status("cudaStreamDestroy")
        if not status:
            self.destroyed_streams.append(_as_int(stream) or 0)
        return status

    def cudaStreamSynchronize(self, stream):  # noqa: N802
        return self._status("cudaStreamSynchronize")

    def cudaEventCreate(self, event):  # noqa: N802
        status = self._status("cudaEventCreate")
        if status:
            return status
        handle = self._handle()
        self.events.append(handle)
        event._obj.value = handle
        return 0

    def cudaEventRecord(self, event, stream):  # noqa: N802
        return self._status("cudaEventRecord")

    def cudaEventSynchronize(self, event):  # noqa: N802
        return self._status("cudaEventSynchronize")

    def cudaEventElapsedTime(self, value, start, end):  # noqa: N802
        status = self._status("cudaEventElapsedTime")
        if not status:
            value._obj.value = 2.5
        return status

    def cudaEventDestroy(self, event):  # noqa: N802
        status = self._status("cudaEventDestroy")
        if not status:
            self.destroyed_events.append(_as_int(event) or 0)
        return status

    def cudaGetErrorString(self, status):  # noqa: N802
        return b"fake cuda error"

    def cudaRuntimeGetVersion(self, value):  # noqa: N802
        value._obj.value = 11040
        return 0

    def cudaDeviceSynchronize(self):  # noqa: N802
        return self._status("cudaDeviceSynchronize")


def make_cuda_runtime(fake: FakeCudaLibrary) -> CudaRuntime:
    runtime = CudaRuntime.__new__(CudaRuntime)
    runtime._lib = fake
    runtime.library_path = "<fake libcudart>"
    runtime.error_count = 0
    return runtime


class FakeEngineRunner:
    """Stands in for TensorRTEngineRunner with a controllable output."""

    def __init__(self, output: np.ndarray, *, name: str = "output0", fail: Any = None) -> None:
        self._output = output
        self._name = name
        self._fail = fail
        self.calls = 0
        self.closed = False
        self.per_frame_device_allocation_count = 0
        self.device_allocation_count = 4

    def infer(self, tensor: np.ndarray) -> Tuple[Dict[str, np.ndarray], Any]:
        self.calls += 1
        if self._fail is not None:
            raise self._fail

        class Timing:
            @staticmethod
            def to_dict() -> Dict[str, Any]:
                return {
                    "h2d_ms": 0.5,
                    "tensorrt_enqueue_ms": 0.2,
                    "gpu_execution_ms": 4.0,
                    "d2h_ms": 0.3,
                    "inference_total_ms": 6.0,
                }

        return {self._name: self._output}, Timing()

    def metrics(self) -> Dict[str, Any]:
        return {"engine_execute_count": self.calls, "per_frame_device_allocation_count": 0}

    def close(self) -> None:
        self.closed = True


def channels_first_output(rows, class_count=80):
    anchors = max(1, len(rows))
    matrix = np.zeros((4 + class_count, anchors), dtype=np.float32)
    for index, (cx, cy, w, h, class_id, score) in enumerate(rows):
        matrix[0, index] = cx
        matrix[1, index] = cy
        matrix[2, index] = w
        matrix[3, index] = h
        matrix[4 + class_id, index] = score
    return matrix[None, ...]


class TestCudaRuntimeWrapper(unittest.TestCase):
    def test_allocation_and_round_trip(self) -> None:
        fake = FakeCudaLibrary()
        runtime = make_cuda_runtime(fake)
        stream = runtime.stream_create()
        payload = np.arange(16, dtype=np.float32)
        received = np.zeros_like(payload)
        pointer = runtime.malloc(payload.nbytes)
        runtime.memcpy_htod_async(pointer, payload, payload.nbytes, stream)
        runtime.memcpy_dtoh_async(received, pointer, payload.nbytes, stream)
        runtime.stream_synchronize(stream)
        np.testing.assert_array_equal(payload, received)
        runtime.free(pointer)
        runtime.stream_destroy(stream)
        self.assertIn(pointer, fake.freed)
        self.assertIn(stream, fake.destroyed_streams)
        self.assertEqual(runtime.error_count, 0)

    def test_every_call_is_status_checked(self) -> None:
        for operation in ("cudaMalloc", "cudaStreamCreate", "cudaMemcpyAsync", "cudaEventCreate"):
            fake = FakeCudaLibrary(fail_on=operation)
            runtime = make_cuda_runtime(fake)
            with self.assertRaises(TensorRTRuntimeError) as ctx:
                if operation == "cudaMalloc":
                    runtime.malloc(128)
                elif operation == "cudaStreamCreate":
                    runtime.stream_create()
                elif operation == "cudaEventCreate":
                    runtime.event_create()
                else:
                    stream = runtime.stream_create()
                    runtime.memcpy_htod_async(1, np.zeros(4, dtype=np.float32), 16, stream)
            self.assertEqual(ctx.exception.classification, "cuda_execution_error")
            self.assertEqual(runtime.error_count, 1)

    def test_event_timing(self) -> None:
        fake = FakeCudaLibrary()
        runtime = make_cuda_runtime(fake)
        stream = runtime.stream_create()
        start = runtime.event_create()
        end = runtime.event_create()
        runtime.event_record(start, stream)
        runtime.event_record(end, stream)
        runtime.event_synchronize(end)
        self.assertAlmostEqual(runtime.event_elapsed_ms(start, end), 2.5, places=3)
        runtime.event_destroy(start)
        runtime.event_destroy(end)
        self.assertEqual(len(fake.destroyed_events), 2)

    def test_runtime_version_and_describe(self) -> None:
        runtime = make_cuda_runtime(FakeCudaLibrary())
        self.assertEqual(runtime.runtime_version(), "11.4")
        described = runtime.describe()
        self.assertEqual(described["cuda_allocator_backend"], "ctypes_cudart")
        self.assertFalse(described["pycuda_used"])
        self.assertFalse(described["pycuda_auto_installed"])

    def test_free_of_null_pointer_is_a_no_op(self) -> None:
        fake = FakeCudaLibrary()
        runtime = make_cuda_runtime(fake)
        runtime.free(0)
        self.assertNotIn("cudaFree", fake.calls)


class TestPreflight(unittest.TestCase):
    def test_tensorrt_preflight_never_raises(self) -> None:
        report = tensorrt_preflight()
        self.assertIn("tensorrt_available", report)
        self.assertFalse(report["auto_install_performed"])

    def test_cuda_preflight_never_raises_and_never_installs(self) -> None:
        report = cuda_preflight()
        self.assertIn("cuda_allocator_backend", report)
        self.assertFalse(report["auto_install_performed"])

    def test_library_search_is_read_only(self) -> None:
        # Returns a path or None; must never raise on a machine without CUDA.
        result = find_cuda_runtime_library()
        self.assertTrue(result is None or isinstance(result, str))

    def test_unsupported_binding_dtype_is_classified(self) -> None:
        with self.assertRaises(TensorRTRuntimeError) as ctx:
            trt_dtype_to_numpy("DataType.UINT4")
        self.assertEqual(ctx.exception.classification, "engine_binding_mismatch")

    def test_known_binding_dtypes_map(self) -> None:
        self.assertIs(trt_dtype_to_numpy("DataType.FLOAT"), np.float32)
        self.assertIs(trt_dtype_to_numpy("DataType.HALF"), np.float16)
        self.assertIs(trt_dtype_to_numpy("DataType.INT32"), np.int32)


class TestBackendWithFakeRunner(unittest.TestCase):
    def _backend(self, runner) -> TensorRTPerceptionBackend:
        return TensorRTPerceptionBackend(
            runner,
            input_contract=InputContract(),
            output_contract=OutputContract(layout="channels_first", class_count=80),
            profile=PostprocessProfile(),
            class_names=["c%d" % index for index in range(80)],
        )

    def test_detect_returns_validated_detections(self) -> None:
        runner = FakeEngineRunner(channels_first_output([(100.0, 100.0, 40.0, 40.0, 5, 0.8)]))
        backend = self._backend(runner)
        detections, elapsed = backend.detect(np.full((360, 640, 3), 100, dtype=np.uint8))
        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0].class_id, 5)
        self.assertGreaterEqual(elapsed, 0)
        self.assertEqual(runner.calls, 1)
        self.assertFalse(backend.fallback_used)
        self.assertEqual(backend.inference_count, 1)

    def test_metadata_declares_no_fallback(self) -> None:
        backend = self._backend(FakeEngineRunner(channels_first_output([])))
        payload = backend.metadata()
        self.assertEqual(payload["backend"], "tensorrt")
        self.assertFalse(payload["fallback_used"])
        self.assertEqual(payload["precision"], "fp16")

    def test_engine_failure_propagates_and_never_falls_back(self) -> None:
        runner = FakeEngineRunner(
            channels_first_output([]),
            fail=TensorRTRuntimeError("engine_execute_failed", "boom"),
        )
        backend = self._backend(runner)
        with self.assertRaises(TensorRTPerceptionError) as ctx:
            backend.detect(np.zeros((360, 640, 3), dtype=np.uint8))
        self.assertEqual(ctx.exception.classification, "engine_execute_failed")
        self.assertEqual(backend.failure_count, 1)
        self.assertFalse(backend.fallback_used)

    def test_missing_output_name_falls_back_to_the_only_output(self) -> None:
        runner = FakeEngineRunner(
            channels_first_output([(100.0, 100.0, 40.0, 40.0, 1, 0.9)]), name="renamed"
        )
        backend = self._backend(runner)
        detections, _ = backend.detect(np.full((360, 640, 3), 90, dtype=np.uint8))
        self.assertEqual(len(detections), 1)

    def test_timing_fields_are_recorded(self) -> None:
        backend = self._backend(FakeEngineRunner(channels_first_output([])))
        backend.detect(np.full((360, 640, 3), 120, dtype=np.uint8))
        for key in ("preprocess_ms", "postprocess_ms", "frame_to_perception_ms", "gpu_execution_ms"):
            self.assertIn(key, backend.last_timing)

    def test_close_releases_the_runner(self) -> None:
        runner = FakeEngineRunner(channels_first_output([]))
        self._backend(runner).close()
        self.assertTrue(runner.closed)


if __name__ == "__main__":
    unittest.main()
