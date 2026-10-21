from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from config import Settings
from infrastructure.cancellation import JobCancelledError
from infrastructure.resources import ResourceKind, ResourceManager
from models import (
    AcquisitionStrategy,
    EntitlementState,
    LoginState,
    MediaAvailability,
    Video,
)
from pipeline.acquire import (
    acquire_video,
    acquire_video_details,
    acquisition_from_video,
)


class AcquisitionContractTests(unittest.TestCase):
    def test_local_acquisition_is_persisted_and_legacy_api_is_compatible(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_path = root / "sample.mp4"
            media_path.write_bytes(b"test")
            settings = Settings(
                base_dir=root,
                output_dir=root / "output",
                cache_dir=root / "cache",
                logs_dir=root / "logs",
            )

            result = acquire_video_details(str(media_path), settings)
            legacy_video = acquire_video(str(media_path), settings)

            self.assertEqual(
                result.selected_strategy,
                AcquisitionStrategy.LOCAL_FILE,
            )
            self.assertEqual(
                result.assessment.login_state,
                LoginState.NOT_REQUIRED,
            )
            self.assertEqual(
                result.assessment.media_availability,
                MediaAvailability.LOCAL_MEDIA,
            )
            self.assertEqual(legacy_video.video_path, media_path)
            self.assertTrue(result.manifest_path and result.manifest_path.exists())
            payload = json.loads(
                result.manifest_path.read_text(encoding="utf-8")
            )
            self.assertEqual(payload["schema_version"], "1.0")
            self.assertEqual(payload["selected_strategy"], "local_file")

    def test_acquired_subtitle_has_explicit_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subtitle_path = root / "subtitle.srt"
            subtitle_path.write_text("subtitle", encoding="utf-8")
            settings = Settings(
                base_dir=root,
                output_dir=root / "output",
                cache_dir=root / "cache",
                logs_dir=root / "logs",
            )
            video = Video(
                source_url="https://example.test/video",
                platform="custom",
                video_id="demo",
                title="Demo",
                subtitle_path=subtitle_path,
            )

            result = acquisition_from_video(video, settings)

            self.assertEqual(
                result.selected_strategy,
                AcquisitionStrategy.PLATFORM_SUBTITLE,
            )
            self.assertEqual(
                result.assessment.entitlement_state,
                EntitlementState.ALLOWED,
            )
            self.assertEqual(result.artifacts[0].kind, "subtitle")


class ResourceManagerTests(unittest.TestCase):
    def test_cpu_limit_is_enforced(self) -> None:
        manager = ResourceManager(
            network_slots=1,
            cpu_heavy_slots=2,
            gpu_slots=1,
            acquire_timeout=2,
        )
        state_lock = threading.Lock()
        active = 0
        maximum = 0

        def work() -> None:
            nonlocal active, maximum
            with manager.lease(ResourceKind.CPU_HEAVY, owner="test"):
                with state_lock:
                    active += 1
                    maximum = max(maximum, active)
                time.sleep(0.03)
                with state_lock:
                    active -= 1

        threads = [threading.Thread(target=work) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(maximum, 2)
        self.assertEqual(manager.snapshot()["active"]["cpu_heavy"], 0)

    def test_same_thread_lease_is_reentrant(self) -> None:
        manager = ResourceManager(
            network_slots=1,
            cpu_heavy_slots=1,
            gpu_slots=1,
            acquire_timeout=0.1,
        )
        with manager.lease(ResourceKind.CPU_HEAVY, owner="outer"):
            with manager.lease(
                ResourceKind.CPU_HEAVY,
                owner="inner",
            ) as lease:
                self.assertTrue(lease.reentrant)

    def test_waiting_for_resource_can_be_cancelled_promptly(self) -> None:
        manager = ResourceManager(
            network_slots=1,
            cpu_heavy_slots=1,
            gpu_slots=1,
            acquire_timeout=30,
        )
        cancel = threading.Event()
        errors: list[Exception] = []

        def wait_for_slot() -> None:
            try:
                with manager.lease(
                    ResourceKind.CPU_HEAVY,
                    owner="waiting",
                    cancel_requested=cancel.is_set,
                ):
                    self.fail("cancelled waiter acquired the slot")
            except Exception as exc:
                errors.append(exc)

        with manager.lease(ResourceKind.CPU_HEAVY, owner="holder"):
            thread = threading.Thread(target=wait_for_slot)
            thread.start()
            time.sleep(0.1)
            cancel.set()
            thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], JobCancelledError)
        self.assertEqual(manager.snapshot()["waiting"]["cpu_heavy"], 0)

    def test_gpu_family_transition_releases_previous_models(self) -> None:
        manager = ResourceManager(
            network_slots=1,
            cpu_heavy_slots=1,
            gpu_slots=1,
            acquire_timeout=1,
        )
        released: list[str] = []
        manager.register_gpu_family(
            "whisper",
            lambda: released.append("whisper"),
        )
        manager.register_gpu_family(
            "openclip",
            lambda: released.append("openclip"),
        )

        with manager.lease(
            ResourceKind.GPU_INFERENCE,
            owner="first",
            family="whisper",
        ):
            pass
        with manager.lease(
            ResourceKind.GPU_INFERENCE,
            owner="second",
            family="openclip",
        ):
            pass

        self.assertEqual(released, ["whisper"])
        self.assertEqual(manager.snapshot()["gpu_family"], "openclip")


if __name__ == "__main__":
    unittest.main()
