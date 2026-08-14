"""Phase 13C TensorRT 8.5 runtime with a ctypes CUDA-runtime allocator.

The Jetson venv has TensorRT 8.5.2.2 but **no PyCUDA and no cuda-python**, and
Phase 13C is forbidden from installing either. This module therefore drives the
CUDA runtime directly through ``ctypes`` over the installed ``libcudart``, and
falls back to PyCUDA only when a preflight proves it is already installed.

Design rules enforced here:

* one reusable CUDA stream per engine;
* device and host buffers allocated **once** per engine/profile — never per
  frame (``per_frame_device_allocation_count`` must stay 0);
* every CUDA call is status-checked;
* deterministic cleanup with no device-memory leak;
* binding dtype/shape validated against the declared contract;
* TensorRT 8 binding API only (``num_bindings`` / ``binding_is_input`` /
  ``get_binding_shape`` / ``set_binding_shape`` / ``execute_async_v2``) — no
  TensorRT 10-only calls;
* batch size 1 only in this phase.

Import stays safe when TensorRT or CUDA are absent so Gate A can run on the PC.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import ctypes
import glob
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

TENSORRT_MAJOR_REQUIRED = 8
DEFAULT_WORKSPACE_BYTES = 1 << 30  # 1 GiB
DEFAULT_BATCH_SIZE = 1

#: cudaMemcpyKind
CUDA_MEMCPY_HOST_TO_DEVICE = 1
CUDA_MEMCPY_DEVICE_TO_HOST = 2

_CUDART_CANDIDATES = (
    "libcudart.so",
    "libcudart.so.11.0",
    "libcudart.so.11",
    "libcudart.so.12",
    "cudart64_110.dll",
    "cudart64_12.dll",
)
_CUDART_SEARCH_DIRS = (
    "/usr/local/cuda/lib64",
    "/usr/local/cuda/targets/aarch64-linux/lib",
    "/usr/lib/aarch64-linux-gnu",
    "/usr/lib/x86_64-linux-gnu",
)


class TensorRTRuntimeError(RuntimeError):
    """TensorRT/CUDA runtime failure carrying a Phase 13C classification."""

    def __init__(self, classification: str, message: str) -> None:
        super().__init__("%s: %s" % (classification, message))
        self.classification = classification
        self.message = message


# ── CUDA runtime via ctypes ─────────────────────────────────────────────────


def find_cuda_runtime_library() -> Optional[str]:
    """Locate ``libcudart`` without importing any Python CUDA binding."""

    explicit = os.environ.get("MA_VLNA_CUDART_PATH", "").strip()
    if explicit and os.path.isfile(explicit):
        return explicit
    for directory in _CUDART_SEARCH_DIRS:
        if not os.path.isdir(directory):
            continue
        for name in _CUDART_CANDIDATES:
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                return candidate
        matches = sorted(glob.glob(os.path.join(directory, "libcudart.so*")))
        if matches:
            return matches[-1]
    for name in _CUDART_CANDIDATES:
        try:
            handle = ctypes.CDLL(name)
        except OSError:
            continue
        return getattr(handle, "_name", name)
    return None


class CudaRuntime:
    """Narrow ctypes wrapper over the installed CUDA runtime library."""

    def __init__(self, library_path: Optional[str] = None) -> None:
        resolved = library_path or find_cuda_runtime_library()
        if not resolved:
            raise TensorRTRuntimeError(
                "cuda_runtime_unavailable", "libcudart could not be located"
            )
        try:
            self._lib = ctypes.CDLL(resolved)
        except OSError as exc:
            raise TensorRTRuntimeError("cuda_runtime_unavailable", repr(exc))
        self.library_path = resolved
        self.error_count = 0
        self._bind()

    def _bind(self) -> None:
        lib = self._lib
        lib.cudaMalloc.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_size_t]
        lib.cudaMalloc.restype = ctypes.c_int
        lib.cudaFree.argtypes = [ctypes.c_void_p]
        lib.cudaFree.restype = ctypes.c_int
        lib.cudaMemcpyAsync.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_int,
            ctypes.c_void_p,
        ]
        lib.cudaMemcpyAsync.restype = ctypes.c_int
        lib.cudaStreamCreate.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        lib.cudaStreamCreate.restype = ctypes.c_int
        lib.cudaStreamDestroy.argtypes = [ctypes.c_void_p]
        lib.cudaStreamDestroy.restype = ctypes.c_int
        lib.cudaStreamSynchronize.argtypes = [ctypes.c_void_p]
        lib.cudaStreamSynchronize.restype = ctypes.c_int
        lib.cudaEventCreate.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        lib.cudaEventCreate.restype = ctypes.c_int
        lib.cudaEventRecord.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.cudaEventRecord.restype = ctypes.c_int
        lib.cudaEventSynchronize.argtypes = [ctypes.c_void_p]
        lib.cudaEventSynchronize.restype = ctypes.c_int
        lib.cudaEventElapsedTime.argtypes = [
            ctypes.POINTER(ctypes.c_float),
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        lib.cudaEventElapsedTime.restype = ctypes.c_int
        lib.cudaEventDestroy.argtypes = [ctypes.c_void_p]
        lib.cudaEventDestroy.restype = ctypes.c_int
        lib.cudaGetErrorString.argtypes = [ctypes.c_int]
        lib.cudaGetErrorString.restype = ctypes.c_char_p
        lib.cudaRuntimeGetVersion.argtypes = [ctypes.POINTER(ctypes.c_int)]
        lib.cudaRuntimeGetVersion.restype = ctypes.c_int
        lib.cudaDeviceSynchronize.argtypes = []
        lib.cudaDeviceSynchronize.restype = ctypes.c_int

    def _check(self, status: int, operation: str) -> None:
        if status != 0:
            self.error_count += 1
            try:
                text = self._lib.cudaGetErrorString(status).decode("utf-8", "replace")
            except Exception:  # pragma: no cover - defensive
                text = "unknown"
            raise TensorRTRuntimeError(
                "cuda_execution_error", "%s failed (status=%d): %s" % (operation, status, text)
            )

    # ── memory ──────────────────────────────────────────────────────────────

    def malloc(self, size_bytes: int) -> int:
        pointer = ctypes.c_void_p()
        self._check(self._lib.cudaMalloc(ctypes.byref(pointer), ctypes.c_size_t(size_bytes)),
                    "cudaMalloc")
        if not pointer.value:
            raise TensorRTRuntimeError("cuda_execution_error", "cudaMalloc returned NULL")
        return int(pointer.value)

    def free(self, pointer: int) -> None:
        if pointer:
            self._check(self._lib.cudaFree(ctypes.c_void_p(pointer)), "cudaFree")

    def memcpy_htod_async(self, device: int, host: Any, size_bytes: int, stream: int) -> None:
        self._check(
            self._lib.cudaMemcpyAsync(
                ctypes.c_void_p(device),
                host.ctypes.data_as(ctypes.c_void_p),
                ctypes.c_size_t(size_bytes),
                ctypes.c_int(CUDA_MEMCPY_HOST_TO_DEVICE),
                ctypes.c_void_p(stream),
            ),
            "cudaMemcpyAsync(H2D)",
        )

    def memcpy_dtoh_async(self, host: Any, device: int, size_bytes: int, stream: int) -> None:
        self._check(
            self._lib.cudaMemcpyAsync(
                host.ctypes.data_as(ctypes.c_void_p),
                ctypes.c_void_p(device),
                ctypes.c_size_t(size_bytes),
                ctypes.c_int(CUDA_MEMCPY_DEVICE_TO_HOST),
                ctypes.c_void_p(stream),
            ),
            "cudaMemcpyAsync(D2H)",
        )

    # ── stream / events ─────────────────────────────────────────────────────

    def stream_create(self) -> int:
        stream = ctypes.c_void_p()
        self._check(self._lib.cudaStreamCreate(ctypes.byref(stream)), "cudaStreamCreate")
        return int(stream.value or 0)

    def stream_destroy(self, stream: int) -> None:
        if stream:
            self._check(self._lib.cudaStreamDestroy(ctypes.c_void_p(stream)), "cudaStreamDestroy")

    def stream_synchronize(self, stream: int) -> None:
        self._check(
            self._lib.cudaStreamSynchronize(ctypes.c_void_p(stream)), "cudaStreamSynchronize"
        )

    def event_create(self) -> int:
        event = ctypes.c_void_p()
        self._check(self._lib.cudaEventCreate(ctypes.byref(event)), "cudaEventCreate")
        return int(event.value or 0)

    def event_record(self, event: int, stream: int) -> None:
        self._check(
            self._lib.cudaEventRecord(ctypes.c_void_p(event), ctypes.c_void_p(stream)),
            "cudaEventRecord",
        )

    def event_synchronize(self, event: int) -> None:
        self._check(self._lib.cudaEventSynchronize(ctypes.c_void_p(event)), "cudaEventSynchronize")

    def event_elapsed_ms(self, start: int, end: int) -> float:
        value = ctypes.c_float()
        self._check(
            self._lib.cudaEventElapsedTime(
                ctypes.byref(value), ctypes.c_void_p(start), ctypes.c_void_p(end)
            ),
            "cudaEventElapsedTime",
        )
        return float(value.value)

    def event_destroy(self, event: int) -> None:
        if event:
            self._check(self._lib.cudaEventDestroy(ctypes.c_void_p(event)), "cudaEventDestroy")

    def runtime_version(self) -> str:
        value = ctypes.c_int()
        status = self._lib.cudaRuntimeGetVersion(ctypes.byref(value))
        if status != 0:
            return ""
        raw = int(value.value)
        return "%d.%d" % (raw // 1000, (raw % 1000) // 10)

    def describe(self) -> Dict[str, Any]:
        return {
            "cuda_allocator_backend": "ctypes_cudart",
            "cudart_library_path": self.library_path,
            "cuda_runtime_version": self.runtime_version(),
            "cuda_error_count": self.error_count,
            "pycuda_used": False,
            "pycuda_auto_installed": False,
        }


def cuda_preflight() -> Dict[str, Any]:
    """Report which CUDA allocator backends are available, installing nothing."""

    report = {
        "pycuda_available": False,
        "cuda_python_available": False,
        "cudart_library_path": None,
        "cuda_runtime_version": "",
        "cuda_allocator_backend": "unavailable",
        "cuda_round_trip_verified": False,
        "auto_install_performed": False,
        "error": None,
    }  # type: Dict[str, Any]
    try:
        import pycuda  # noqa: F401  # type: ignore[import-not-found]

        report["pycuda_available"] = True
    except Exception:
        pass
    try:
        import cuda  # noqa: F401  # type: ignore[import-not-found]

        report["cuda_python_available"] = True
    except Exception:
        pass

    library = find_cuda_runtime_library()
    report["cudart_library_path"] = library
    if not library:
        report["error"] = "libcudart not found"
        return report
    try:
        runtime = CudaRuntime(library)
    except TensorRTRuntimeError as exc:
        report["error"] = exc.message
        return report
    report["cuda_runtime_version"] = runtime.runtime_version()
    report["cuda_allocator_backend"] = "ctypes_cudart"

    # Bounded round trip: allocate, H2D, D2H, compare, free.
    stream = 0
    device_pointer = 0
    try:
        payload = np.arange(256, dtype=np.float32)
        received = np.zeros_like(payload)
        stream = runtime.stream_create()
        device_pointer = runtime.malloc(payload.nbytes)
        runtime.memcpy_htod_async(device_pointer, payload, payload.nbytes, stream)
        runtime.memcpy_dtoh_async(received, device_pointer, payload.nbytes, stream)
        runtime.stream_synchronize(stream)
        report["cuda_round_trip_verified"] = bool(np.array_equal(payload, received))
    except TensorRTRuntimeError as exc:
        report["error"] = exc.message
    finally:
        try:
            if device_pointer:
                runtime.free(device_pointer)
            if stream:
                runtime.stream_destroy(stream)
        except TensorRTRuntimeError:
            pass
    report["cuda_error_count"] = runtime.error_count
    return report


# ── TensorRT ────────────────────────────────────────────────────────────────


def tensorrt_preflight() -> Dict[str, Any]:
    """Report the installed TensorRT without requiring it to be present."""

    report = {
        "tensorrt_available": False,
        "tensorrt_version": "",
        "tensorrt_major": 0,
        "tensorrt_api": "unknown",
        "auto_install_performed": False,
        "error": None,
    }  # type: Dict[str, Any]
    try:
        import tensorrt as trt  # type: ignore[import-not-found]
    except Exception as exc:
        report["error"] = repr(exc)[:200]
        return report
    version = str(getattr(trt, "__version__", ""))
    report["tensorrt_available"] = True
    report["tensorrt_version"] = version
    try:
        report["tensorrt_major"] = int(version.split(".")[0])
    except (ValueError, IndexError):
        report["tensorrt_major"] = 0
    # TensorRT 8 exposes the binding API; TensorRT 10 replaced it with tensors.
    report["tensorrt_api"] = (
        "binding_api" if hasattr(trt.ICudaEngine, "num_bindings") else "tensor_api"
    )
    return report


_TRT_TO_NUMPY = {
    "FLOAT": np.float32,
    "HALF": np.float16,
    "INT8": np.int8,
    "INT32": np.int32,
    "BOOL": np.bool_,
}


def trt_dtype_to_numpy(dtype: Any) -> Any:
    name = str(dtype).rsplit(".", 1)[-1].upper()
    if name not in _TRT_TO_NUMPY:
        raise TensorRTRuntimeError("engine_binding_mismatch", "unsupported binding dtype %s" % name)
    return _TRT_TO_NUMPY[name]


@dataclass
class BindingInfo:
    """One engine binding, resolved at load time and never re-derived."""

    index: int
    name: str
    is_input: bool
    shape: List[int]
    dtype: str
    numpy_dtype: Any
    element_count: int
    nbytes: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "is_input": self.is_input,
            "shape": list(self.shape),
            "dtype": self.dtype,
            "element_count": self.element_count,
            "nbytes": self.nbytes,
        }


@dataclass
class InferenceTiming:
    """Per-inference host and GPU timings, all from ``perf_counter_ns``/events."""

    h2d_ms: float = 0.0
    enqueue_ms: float = 0.0
    gpu_execution_ms: Optional[float] = None
    d2h_ms: float = 0.0
    total_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "h2d_ms": round(self.h2d_ms, 4),
            "tensorrt_enqueue_ms": round(self.enqueue_ms, 4),
            "gpu_execution_ms": round(self.gpu_execution_ms, 4)
            if self.gpu_execution_ms is not None
            else None,
            "d2h_ms": round(self.d2h_ms, 4),
            "inference_total_ms": round(self.total_ms, 4),
        }


class TensorRTEngineRunner:
    """Load a target-built engine and run bounded batch-1 FP16 inference."""

    def __init__(
        self,
        engine_path: str,
        *,
        expected_input_shape: Optional[List[int]] = None,
        expected_input_name: Optional[str] = None,
        cuda_runtime: Optional[CudaRuntime] = None,
        enable_gpu_timing: bool = True,
        logger_severity: str = "ERROR",
    ) -> None:
        try:
            import tensorrt as trt  # type: ignore[import-not-found]
        except Exception as exc:
            raise TensorRTRuntimeError("tensorrt_builder_unavailable", repr(exc)[:200])
        self._trt = trt

        version = str(getattr(trt, "__version__", ""))
        try:
            major = int(version.split(".")[0])
        except (ValueError, IndexError):
            major = 0
        if major != TENSORRT_MAJOR_REQUIRED:
            raise TensorRTRuntimeError(
                "tensorrt_builder_unavailable",
                "Phase 13C targets TensorRT %d, found %s" % (TENSORRT_MAJOR_REQUIRED, version),
            )
        self.tensorrt_version = version

        if not os.path.isfile(engine_path):
            raise TensorRTRuntimeError("engine_missing", "engine not found: %s" % engine_path)
        self.engine_path = engine_path

        severity = getattr(trt.Logger, logger_severity, trt.Logger.ERROR)
        self._logger = trt.Logger(severity)
        with open(engine_path, "rb") as handle:
            plan = handle.read()
        self._runtime = trt.Runtime(self._logger)
        engine = self._runtime.deserialize_cuda_engine(plan)
        if engine is None:
            raise TensorRTRuntimeError(
                "engine_deserialize_failed", "deserialize_cuda_engine returned None"
            )
        self._engine = engine
        self.engine_deserialized = True

        context = engine.create_execution_context()
        if context is None:
            raise TensorRTRuntimeError(
                "engine_deserialize_failed", "create_execution_context returned None"
            )
        self._context = context

        self.cuda = cuda_runtime or CudaRuntime()
        self.enable_gpu_timing = bool(enable_gpu_timing)

        self.bindings = []  # type: List[BindingInfo]
        self.input_bindings = []  # type: List[BindingInfo]
        self.output_bindings = []  # type: List[BindingInfo]
        self.dynamic_shapes = False
        self._device_pointers = []  # type: List[int]
        self._host_outputs = {}  # type: Dict[str, Any]
        self._host_input = None  # type: Any
        self._stream = 0
        self._start_event = 0
        self._end_event = 0

        self.device_allocation_count = 0
        self.host_allocation_count = 0
        self.per_frame_device_allocation_count = 0
        self.engine_execute_count = 0
        self.engine_execute_failure_count = 0
        self.device_memory_bytes = 0
        self.host_buffer_bytes = 0
        self._closed = False

        self._resolve_bindings(expected_input_shape, expected_input_name)
        self._allocate_once()

    # ── setup ───────────────────────────────────────────────────────────────

    def _resolve_bindings(
        self, expected_input_shape: Optional[List[int]], expected_input_name: Optional[str]
    ) -> None:
        trt = self._trt
        engine = self._engine
        count = int(engine.num_bindings)
        if count < 2:
            raise TensorRTRuntimeError(
                "engine_binding_mismatch", "engine exposes %d bindings, expected >= 2" % count
            )

        for index in range(count):
            name = str(engine.get_binding_name(index))
            is_input = bool(engine.binding_is_input(index))
            shape = [int(value) for value in engine.get_binding_shape(index)]
            if any(value < 0 for value in shape):
                self.dynamic_shapes = True
                if is_input and expected_input_shape:
                    shape = [int(value) for value in expected_input_shape]
                    if not self._context.set_binding_shape(index, tuple(shape)):
                        raise TensorRTRuntimeError(
                            "engine_binding_mismatch",
                            "set_binding_shape failed for %s -> %s" % (name, shape),
                        )
                else:
                    raise TensorRTRuntimeError(
                        "engine_binding_mismatch",
                        "dynamic binding %s needs an explicit profile shape" % name,
                    )
            numpy_dtype = trt_dtype_to_numpy(engine.get_binding_dtype(index))
            element_count = 1
            for value in shape:
                element_count *= int(value)
            info = BindingInfo(
                index=index,
                name=name,
                is_input=is_input,
                shape=shape,
                dtype=str(engine.get_binding_dtype(index)).rsplit(".", 1)[-1],
                numpy_dtype=numpy_dtype,
                element_count=element_count,
                nbytes=element_count * int(np.dtype(numpy_dtype).itemsize),
            )
            self.bindings.append(info)
            (self.input_bindings if is_input else self.output_bindings).append(info)

        # Re-read output shapes once every dynamic input shape is fixed.
        if self.dynamic_shapes:
            for info in self.output_bindings:
                resolved = [int(value) for value in self._context.get_binding_shape(info.index)]
                if any(value < 0 for value in resolved):
                    raise TensorRTRuntimeError(
                        "engine_binding_mismatch",
                        "output %s stayed dynamic after profile selection" % info.name,
                    )
                info.shape = resolved
                element_count = 1
                for value in resolved:
                    element_count *= value
                info.element_count = element_count
                info.nbytes = element_count * int(np.dtype(info.numpy_dtype).itemsize)

        if len(self.input_bindings) != 1:
            raise TensorRTRuntimeError(
                "engine_binding_mismatch",
                "Phase 13C supports exactly one input binding, found %d"
                % len(self.input_bindings),
            )
        primary = self.input_bindings[0]
        if expected_input_name and primary.name != expected_input_name:
            raise TensorRTRuntimeError(
                "engine_binding_mismatch",
                "input binding is %r, expected %r" % (primary.name, expected_input_name),
            )
        if expected_input_shape and primary.shape != [int(v) for v in expected_input_shape]:
            raise TensorRTRuntimeError(
                "engine_binding_mismatch",
                "input shape %s does not match declared profile %s"
                % (primary.shape, list(expected_input_shape)),
            )
        if primary.shape and int(primary.shape[0]) != DEFAULT_BATCH_SIZE:
            raise TensorRTRuntimeError(
                "engine_binding_mismatch",
                "Phase 13C supports batch size 1 only, engine declares %d" % primary.shape[0],
            )

    def _allocate_once(self) -> None:
        """All device/host buffers are created here and reused for every frame."""

        self._stream = self.cuda.stream_create()
        if self.enable_gpu_timing:
            try:
                self._start_event = self.cuda.event_create()
                self._end_event = self.cuda.event_create()
            except TensorRTRuntimeError:
                self.enable_gpu_timing = False
                self._start_event = 0
                self._end_event = 0

        self._device_pointers = [0] * len(self.bindings)
        for info in self.bindings:
            pointer = self.cuda.malloc(info.nbytes)
            self._device_pointers[info.index] = pointer
            self.device_allocation_count += 1
            self.device_memory_bytes += info.nbytes

        primary = self.input_bindings[0]
        self._host_input = np.zeros(primary.element_count, dtype=primary.numpy_dtype)
        self.host_allocation_count += 1
        self.host_buffer_bytes += int(self._host_input.nbytes)
        for info in self.output_bindings:
            buffer = np.zeros(info.element_count, dtype=info.numpy_dtype)
            self._host_outputs[info.name] = buffer
            self.host_allocation_count += 1
            self.host_buffer_bytes += int(buffer.nbytes)

    # ── inference ───────────────────────────────────────────────────────────

    def infer(self, tensor: np.ndarray) -> Tuple[Dict[str, np.ndarray], InferenceTiming]:
        """Run one batch-1 inference. Allocates nothing on the device."""

        if self._closed:
            raise TensorRTRuntimeError("engine_execute_failed", "runner is closed")
        primary = self.input_bindings[0]
        if list(tensor.shape) != primary.shape:
            raise TensorRTRuntimeError(
                "input_shape_mismatch",
                "input shape %s does not match binding %s" % (list(tensor.shape), primary.shape),
            )
        if np.dtype(tensor.dtype) != np.dtype(primary.numpy_dtype):
            raise TensorRTRuntimeError(
                "input_dtype_mismatch",
                "input dtype %s does not match binding %s"
                % (tensor.dtype, np.dtype(primary.numpy_dtype)),
            )

        started = time.perf_counter_ns()
        # Reuse the pinned-shape host staging buffer; no per-frame allocation.
        np.copyto(self._host_input, tensor.reshape(-1), casting="no")

        h2d_start = time.perf_counter_ns()
        self.cuda.memcpy_htod_async(
            self._device_pointers[primary.index],
            self._host_input,
            primary.nbytes,
            self._stream,
        )
        h2d_ms = (time.perf_counter_ns() - h2d_start) / 1e6

        gpu_ms = None  # type: Optional[float]
        if self.enable_gpu_timing and self._start_event:
            self.cuda.event_record(self._start_event, self._stream)

        enqueue_start = time.perf_counter_ns()
        ok = self._context.execute_async_v2(
            bindings=[int(pointer) for pointer in self._device_pointers],
            stream_handle=int(self._stream),
        )
        enqueue_ms = (time.perf_counter_ns() - enqueue_start) / 1e6
        if not ok:
            self.engine_execute_failure_count += 1
            raise TensorRTRuntimeError(
                "engine_execute_failed", "execute_async_v2 returned False"
            )

        if self.enable_gpu_timing and self._end_event:
            self.cuda.event_record(self._end_event, self._stream)

        d2h_start = time.perf_counter_ns()
        for info in self.output_bindings:
            self.cuda.memcpy_dtoh_async(
                self._host_outputs[info.name],
                self._device_pointers[info.index],
                info.nbytes,
                self._stream,
            )
        self.cuda.stream_synchronize(self._stream)
        d2h_ms = (time.perf_counter_ns() - d2h_start) / 1e6

        if self.enable_gpu_timing and self._start_event and self._end_event:
            try:
                self.cuda.event_synchronize(self._end_event)
                gpu_ms = self.cuda.event_elapsed_ms(self._start_event, self._end_event)
            except TensorRTRuntimeError:
                gpu_ms = None

        outputs = {
            info.name: self._host_outputs[info.name].reshape(info.shape)
            for info in self.output_bindings
        }
        self.engine_execute_count += 1
        timing = InferenceTiming(
            h2d_ms=h2d_ms,
            enqueue_ms=enqueue_ms,
            gpu_execution_ms=gpu_ms,
            d2h_ms=d2h_ms,
            total_ms=(time.perf_counter_ns() - started) / 1e6,
        )
        return outputs, timing

    # ── teardown / evidence ─────────────────────────────────────────────────

    def close(self) -> None:
        """Deterministic cleanup; safe to call twice."""

        if self._closed:
            return
        self._closed = True
        for index, pointer in enumerate(self._device_pointers):
            if pointer:
                try:
                    self.cuda.free(pointer)
                except TensorRTRuntimeError:
                    pass
                self._device_pointers[index] = 0
        for event in (self._start_event, self._end_event):
            if event:
                try:
                    self.cuda.event_destroy(event)
                except TensorRTRuntimeError:
                    pass
        self._start_event = 0
        self._end_event = 0
        if self._stream:
            try:
                self.cuda.stream_destroy(self._stream)
            except TensorRTRuntimeError:
                pass
            self._stream = 0
        self._host_outputs = {}
        self._host_input = None
        self._context = None
        self._engine = None
        self._runtime = None

    def __enter__(self) -> "TensorRTEngineRunner":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def binding_report(self) -> Dict[str, Any]:
        return {
            "engine_binding_count": len(self.bindings),
            "engine_input_bindings": [item.to_dict() for item in self.input_bindings],
            "engine_output_bindings": [item.to_dict() for item in self.output_bindings],
            "engine_dynamic_shapes": self.dynamic_shapes,
            "engine_deserialization_verified": self.engine_deserialized,
            "engine_binding_contract_verified": True,
        }

    def metrics(self) -> Dict[str, Any]:
        payload = {
            "engine_path": self.engine_path,
            "tensorrt_version": self.tensorrt_version,
            "device_allocation_count": self.device_allocation_count,
            "host_allocation_count": self.host_allocation_count,
            "per_frame_device_allocation_count": self.per_frame_device_allocation_count,
            "engine_execute_count": self.engine_execute_count,
            "engine_execute_failure_count": self.engine_execute_failure_count,
            "device_memory_bytes": self.device_memory_bytes,
            "host_buffer_bytes": self.host_buffer_bytes,
            "gpu_timing_enabled": self.enable_gpu_timing,
        }
        payload.update(self.cuda.describe())
        payload.update(self.binding_report())
        return payload
