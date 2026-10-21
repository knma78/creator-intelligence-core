from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from infrastructure.jobs import (
    JobQueueFullError,
    JobStore,
    LocalJobRunner,
)


class PersistentJobStoreTests(unittest.TestCase):
    def _store(
        self,
        root: Path,
        *,
        queue_capacity: int = 100,
    ) -> JobStore:
        return JobStore(
            root / "jobs.sqlite3",
            queue_capacity=queue_capacity,
        )

    def test_job_and_logs_survive_store_recreation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = self._store(root)
            job = store.create({"source": "BV1test", "mode": "video"})
            store.update(
                job["id"],
                status="running",
                stage="下载",
                progress=30,
                log="正在下载。",
            )

            reopened = self._store(root)
            persisted = reopened.get(job["id"])

        self.assertEqual(persisted["status"], "running")
        self.assertEqual(persisted["stage"], "下载")
        self.assertEqual(persisted["progress"], 30)
        self.assertEqual(
            persisted["logs"],
            ["任务已创建。", "正在下载。"],
        )

    def test_interrupted_running_job_is_requeued_with_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = self._store(root)
            job = store.create({"source": "BV1test"})
            claimed = store.claim_next("worker-before-restart")
            self.assertEqual(claimed["id"], job["id"])
            self.assertEqual(claimed["status"], "running")

            reopened = self._store(root)
            recovered = reopened.recover_interrupted()
            restored = reopened.get(job["id"])
            events = reopened.events(job["id"])

        self.assertEqual(recovered, [job["id"]])
        self.assertEqual(restored["status"], "queued")
        self.assertEqual(restored["stage"], "恢复排队")
        self.assertIn(
            "检测到程序上次中断，任务已重新排队。",
            restored["logs"],
        )
        self.assertEqual(events[-1]["event_type"], "recovered")

    def test_queue_capacity_counts_waiting_and_running_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory), queue_capacity=1)
            store.create({"source": "first"})

            with self.assertRaises(JobQueueFullError):
                store.create({"source": "second"})

    def test_queued_job_is_cancelled_before_worker_can_claim_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            job = store.create({"source": "cancel-before-start"})

            cancelled = store.request_cancel(job["id"])
            claimed = store.claim_next("worker")

        self.assertEqual(cancelled["status"], "cancelled")
        self.assertTrue(cancelled["cancel_requested"])
        self.assertIsNotNone(cancelled["cancel_requested_at"])
        self.assertIsNone(claimed)

    def test_running_job_records_cooperative_cancel_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            job = store.create({"source": "cancel-while-running"})
            store.claim_next("worker")
            detail = {
                "type": "whisper",
                "state": "transcribing",
                "elapsed_seconds": 12,
            }
            store.update(job["id"], progress_detail=detail)

            cancelling = store.request_cancel(job["id"])
            cancel_requested = store.is_cancel_requested(job["id"])
            last_event = store.events(job["id"])[-1]

        self.assertEqual(cancelling["status"], "running")
        self.assertEqual(cancelling["stage"], "正在取消")
        self.assertTrue(cancel_requested)
        self.assertEqual(cancelling["progress_detail"], detail)
        self.assertEqual(last_event["event_type"], "cancel_requested")

    def test_cancel_requested_job_stays_cancelled_after_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            job = store.create({"source": "cancel-before-restart"})
            store.claim_next("worker")
            store.request_cancel(job["id"])

            recovered = store.recover_interrupted()
            restored = store.get(job["id"])

        self.assertEqual(recovered, [])
        self.assertEqual(restored["status"], "cancelled")
        self.assertEqual(restored["stage"], "已取消")

    def test_interactive_capture_is_not_restarted_without_consent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = self._store(root)
            job = store.create(
                {
                    "source": "https://www.bilibili.com/video/BVtest",
                    "allow_playback_capture": True,
                }
            )
            store.claim_next("crashed-worker")

            recovered = store.recover_interrupted()
            restored = store.get(job["id"])
            events = store.events(job["id"])

        self.assertEqual(recovered, [])
        self.assertEqual(restored["status"], "failed")
        self.assertEqual(restored["stage"], "需要重新确认")
        self.assertIn("重新提交", restored["error"])
        self.assertEqual(events[-1]["event_type"], "recovery_blocked")


class LocalJobRunnerTests(unittest.TestCase):
    def test_fixed_worker_count_processes_persisted_queue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "jobs.sqlite3")
            lock = threading.Lock()
            active = 0
            maximum_active = 0

            def execute(job_id: str) -> None:
                nonlocal active, maximum_active
                with lock:
                    active += 1
                    maximum_active = max(maximum_active, active)
                try:
                    time.sleep(0.03)
                    store.update(
                        job_id,
                        status="done",
                        stage="完成",
                        progress=100,
                        result={"ok": True},
                        log="完成。",
                    )
                finally:
                    with lock:
                        active -= 1

            jobs = [
                store.create({"source": f"item-{index}"})
                for index in range(3)
            ]
            runner = LocalJobRunner(
                store,
                execute,
                worker_count=1,
            )
            runner.start()
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    statuses = [
                        store.get(job["id"])["status"]
                        for job in jobs
                    ]
                    if statuses == ["done", "done", "done"]:
                        break
                    time.sleep(0.02)
                else:
                    self.fail(f"jobs did not finish: {statuses}")
            finally:
                runner.shutdown(wait=True)
            attempt_counts = [
                store.get(job["id"])["attempt_count"]
                for job in jobs
            ]

        self.assertEqual(maximum_active, 1)
        self.assertEqual(attempt_counts, [1, 1, 1])

    def test_runner_recovers_and_executes_interrupted_job(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "jobs.sqlite3")
            job = store.create({"source": "recover-me"})
            store.claim_next("crashed-worker")

            def execute(job_id: str) -> None:
                store.update(
                    job_id,
                    status="done",
                    stage="完成",
                    progress=100,
                    result={"recovered": True},
                    log="恢复任务完成。",
                )

            runner = LocalJobRunner(store, execute, worker_count=1)
            recovered = runner.start(recover=True)
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    restored = store.get(job["id"])
                    if restored["status"] == "done":
                        break
                    time.sleep(0.02)
                else:
                    self.fail("recovered job did not finish")
            finally:
                runner.shutdown(wait=True)

        self.assertEqual(recovered, [job["id"]])
        self.assertEqual(restored["attempt_count"], 2)
        self.assertTrue(restored["result"]["recovered"])


if __name__ == "__main__":
    unittest.main()
