"""
Single-threaded executor shared by all native C++ operations
(dlib / face_recognition, MediaPipe).

Running dlib and MediaPipe concurrently in separate threads causes heap
corruption (free(): corrupted unsorted chunks) because both link against
OpenBLAS / TensorFlow Lite and share global state.  Serialising them
through a single worker thread eliminates the race.
"""
from concurrent.futures import ThreadPoolExecutor

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="native")


def get_executor() -> ThreadPoolExecutor:
    return _executor
