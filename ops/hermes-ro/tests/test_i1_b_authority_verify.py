from __future__ import annotations

import importlib.util
import os
from dataclasses import replace
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
LAUNCHER_PATH = ROOT / "ops/hermes-ro/i1_b_authority_verify.py"
INSTALLER_PATH = ROOT / "ops/hermes-ro/install_i1_b_authority_verify.py"
SUDOERS_PATH = ROOT / "ops/hermes-ro/sudoers.d/megabrain-hermes-i1-b-authority-verify"
CANONICAL_VERIFIER_PATH = ROOT / "infra/postgres/security/f6/008_i1_b_web_applicable_enrichment_read_verify.sql"
EXPECTED_BLOB = "b6651e8e9136bcd11faa4912e39df1c8c0099a22"
EXPECTED_SHA = "29f314c06351d2f420aa1df54eea90d3d1b7396b"
EXPECTED_TREE = "49ee708df6ecc790c0e77e011a5d0d6a10f7f994"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_launcher():
    return load_module("i1_b_authority_verify", LAUNCHER_PATH)


def load_installer():
    return load_module("install_i1_b_authority_verify", INSTALLER_PATH)


def canonical_bytes() -> bytes:
    return CANONICAL_VERIFIER_PATH.read_bytes()


class LauncherContractTests(unittest.TestCase):
    def test_zero_argument_invocation_builds_the_fixed_child_command(self) -> None:
        launcher = load_launcher()
        captured: list[tuple[list[str], bytes, dict[str, str]]] = []

        def runner(command: list[str], payload: bytes, environment: dict[str, str]):
            captured.append((command, payload, environment))
            return launcher.ChildResult(0, launcher.expected_pass_report(), b"")

        result = launcher.run([], runner=runner, verifier_bytes=canonical_bytes(), audit=lambda _: True)

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.result_class, "PASS")
        self.assertEqual(captured[0][0], launcher.FIXED_DOCKER_COMMAND)
        self.assertEqual(captured[0][0][5], "megabrain-postgres")

    def test_arguments_are_rejected_before_any_child_execution(self) -> None:
        launcher = load_launcher()
        calls = 0

        def runner(*_args):
            nonlocal calls
            calls += 1
            raise AssertionError("runner must not execute")

        for supplied in (["SELECT 1"], ["/tmp/verifier.sql"], ["megabrain-postgres"]):
            result = launcher.run(supplied, runner=runner, verifier_bytes=canonical_bytes(), audit=lambda _: True)
            self.assertEqual(result.exit_code, 64)
            self.assertEqual(result.result_class, "BOUNDARY_FAILURE")
        self.assertEqual(calls, 0)

    def test_environment_poisoning_is_not_passed_to_child(self) -> None:
        launcher = load_launcher()
        captured: dict[str, str] = {}
        original = dict(os.environ)
        os.environ.update({
            "DOCKER_HOST": "tcp://attacker.invalid:2375",
            "PGPASSWORD": "do-not-pass",
            "PGHOST": "attacker.invalid",
            "LD_PRELOAD": "/tmp/evil.so",
            "PYTHONPATH": "/tmp/evil",
        })
        try:
            def runner(_command, _payload, environment):
                captured.update(environment)
                return launcher.ChildResult(0, launcher.expected_pass_report(), b"")

            result = launcher.run([], runner=runner, verifier_bytes=canonical_bytes(), audit=lambda _: True)
        finally:
            os.environ.clear()
            os.environ.update(original)

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(captured, launcher.SANITIZED_ENV)
        for name in ("DOCKER_HOST", "PGPASSWORD", "PGHOST", "LD_PRELOAD", "PYTHONPATH"):
            self.assertNotIn(name, captured)

    def test_fixed_child_command_has_no_caller_interpolation(self) -> None:
        launcher = load_launcher()
        command = launcher.FIXED_DOCKER_COMMAND
        self.assertEqual(command[:7], ["/usr/bin/docker", "exec", "-i", "--user", "postgres", "megabrain-postgres", "/bin/sh"])
        self.assertEqual(command[7], "-c")
        self.assertEqual(command[8], 'exec psql -q -X --no-password -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"')
        self.assertNotIn(";", command[8])
        self.assertNotIn("$1", command[8])

    def test_one_psql_session_starts_read_only_contains_exact_verifier_and_rolls_back_on_pass(self) -> None:
        launcher = load_launcher()
        captured: list[bytes] = []

        def runner(_command, payload, _environment):
            captured.append(payload)
            return launcher.ChildResult(0, launcher.expected_pass_report(), b"")

        result = launcher.run([], runner=runner, verifier_bytes=canonical_bytes(), audit=lambda _: True)

        self.assertEqual(result.exit_code, 0)
        self.assertTrue(captured[0].startswith(b"BEGIN TRANSACTION READ ONLY;\n"))
        self.assertIn(canonical_bytes(), captured[0])
        self.assertTrue(captured[0].endswith(b"\nROLLBACK;\n"))

    def test_verifier_report_uses_postgresql_boolean_text_grammar(self) -> None:
        launcher = load_launcher()
        report = launcher.expected_pass_report().decode("ascii")
        self.assertIn("WEB_I1_B_SCHEMA_USAGE | PASS | t | t", report)
        self.assertIn("WEB_I1_B_SCHEMA_CREATE | PASS | f | f", report)

    def test_assertion_failure_preserves_exit_three_and_named_failures(self) -> None:
        launcher = load_launcher()
        lines = launcher.expected_pass_report().decode("ascii").splitlines()
        lines[0] = lines[0].replace("PASS", "FAIL").replace("t | t", "t | f")

        result = launcher.run(
            [],
            runner=lambda *_: launcher.ChildResult(3, "\n".join(lines).encode("ascii"), b""),
            verifier_bytes=canonical_bytes(),
            audit=lambda _: True,
        )

        self.assertEqual(result.exit_code, 3)
        self.assertEqual(result.result_class, "VERIFIER_ASSERTION_FAILURE")
        self.assertIn("result=VERIFIER_ASSERTION_FAILURE", result.output)

    def test_runtime_failure_and_credential_like_stderr_are_not_relayed(self) -> None:
        launcher = load_launcher()
        secret_like_stderr = b"password=do-not-disclose host=private.example"

        result = launcher.run(
            [],
            runner=lambda *_: launcher.ChildResult(9, launcher.expected_pass_report(), secret_like_stderr),
            verifier_bytes=canonical_bytes(),
            audit=lambda _: True,
        )

        self.assertEqual(result.exit_code, 9)
        self.assertEqual(result.result_class, "RUNTIME_FAILURE")
        self.assertNotIn("do-not-disclose", result.output)
        self.assertNotIn("private.example", result.output)

    def test_unknown_or_oversized_output_fails_closed(self) -> None:
        launcher = load_launcher()
        for stdout in (b"unexpected output\n", b"x" * (launcher.MAX_OUTPUT_BYTES + 1)):
            result = launcher.run(
                [],
                runner=lambda *_args, output=stdout: launcher.ChildResult(0, output, b""),
                verifier_bytes=canonical_bytes(),
                audit=lambda _: True,
            )
            self.assertEqual(result.exit_code, 70)
            self.assertEqual(result.result_class, "OUTPUT_GRAMMAR_FAILURE")

    def test_audit_failure_is_non_success(self) -> None:
        launcher = load_launcher()
        result = launcher.run(
            [],
            runner=lambda *_: launcher.ChildResult(0, launcher.expected_pass_report(), b""),
            verifier_bytes=canonical_bytes(),
            audit=lambda _: False,
        )
        self.assertEqual(result.exit_code, 71)
        self.assertEqual(result.result_class, "AUDIT_FAILURE")


class VerifierIdentityTests(unittest.TestCase):
    def test_correct_canonical_blob_fixture_is_accepted(self) -> None:
        launcher = load_launcher()
        metadata = launcher.VerifierMetadata(stat.S_IFREG | 0o600, 0, 0)
        self.assertEqual(launcher.git_blob_sha1(canonical_bytes()), EXPECTED_BLOB)
        self.assertEqual(
            launcher.validate_verifier_bytes(canonical_bytes(), metadata),
            canonical_bytes(),
        )

    def test_wrong_blob_and_one_byte_modification_are_rejected(self) -> None:
        launcher = load_launcher()
        metadata = launcher.VerifierMetadata(stat.S_IFREG | 0o600, 0, 0)
        modified = canonical_bytes() + b"\n"
        for candidate in (b"not the canonical verifier", modified):
            with self.assertRaises(ValueError):
                launcher.validate_verifier_bytes(candidate, metadata)

    def test_symlink_owner_group_and_mode_boundaries_are_rejected(self) -> None:
        launcher = load_launcher()
        invalid_metadata = (
            launcher.VerifierMetadata(stat.S_IFLNK | 0o600, 0, 0),
            launcher.VerifierMetadata(stat.S_IFREG | 0o600, 1001, 0),
            launcher.VerifierMetadata(stat.S_IFREG | 0o600, 0, 1001),
            launcher.VerifierMetadata(stat.S_IFREG | 0o640, 0, 0),
        )
        for metadata in invalid_metadata:
            with self.assertRaises(ValueError):
                launcher.validate_verifier_bytes(canonical_bytes(), metadata)


class SudoersTemplateTests(unittest.TestCase):
    def test_template_grants_only_the_exact_no_argument_launcher(self) -> None:
        text = SUDOERS_PATH.read_text(encoding="ascii")
        self.assertIn("NOSETENV", text)
        self.assertIn("NOPASSWD", text)
        self.assertIn("/usr/local/sbin/megabrain-hermes-i1-b-authority-verify \"\"", text)
        self.assertNotIn("*", text)
        for forbidden in ("docker", "psql", "python", "sh", "bash"):
            self.assertNotIn(forbidden, text.lower())


class InstallerContractTests(unittest.TestCase):
    def test_installer_rejects_non_root_and_wrong_canonical_identity(self) -> None:
        installer = load_installer()
        with self.assertRaises(PermissionError):
            installer.validate_install_preflight(1001, EXPECTED_SHA, EXPECTED_TREE, EXPECTED_BLOB)
        for sha, tree, blob in (("0" * 40, EXPECTED_TREE, EXPECTED_BLOB), (EXPECTED_SHA, "0" * 40, EXPECTED_BLOB), (EXPECTED_SHA, EXPECTED_TREE, "0" * 40)):
            with self.assertRaises(ValueError):
                installer.validate_install_preflight(0, sha, tree, blob)

    def test_installer_main_rejects_command_line_arguments(self) -> None:
        installer = load_installer()
        original_argv = sys.argv
        sys.argv = ["installer", "unexpected"]
        try:
            with self.assertRaises(SystemExit):
                installer.main()
        finally:
            sys.argv = original_argv

    def test_installer_does_not_repermission_existing_system_parents(self) -> None:
        self.assertNotIn("os.chmod(destination.parent", INSTALLER_PATH.read_text(encoding="utf-8"))

    def test_installer_refuses_symlink_destination_and_rollback_is_dedicated(self) -> None:
        installer = load_installer()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.write_text("target", encoding="ascii")
            link = root / "link"
            link.symlink_to(target)
            self.assertFalse(installer.destination_is_safe(link))
        self.assertEqual(
            set(installer.rollback_paths()),
            {
                installer.RUNTIME_LAUNCHER_PATH,
                installer.RUNTIME_VERIFIER_PATH,
                installer.RUNTIME_SUDOERS_PATH,
                installer.RUNTIME_AUDIT_LOG_PATH,
            },
        )


class InstallerRollbackHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.installer = load_installer()

    def _root_file_metadata(
        self,
        path: Path,
        *,
        mode: int,
        file_type: int = stat.S_IFREG,
        uid: int = 0,
        gid: int = 0,
    ) -> SimpleNamespace:
        actual = os.lstat(path)
        return SimpleNamespace(
            st_mode=file_type | mode,
            st_uid=uid,
            st_gid=gid,
            st_size=actual.st_size,
            st_dev=actual.st_dev,
            st_ino=actual.st_ino,
        )

    def _safe_delete(self, spec, *, metadata=None) -> None:
        metadata = metadata or self._root_file_metadata(spec.path, mode=spec.mode)
        self.installer._safe_delete_runtime_file(
            spec,
            lstat=lambda _path: metadata,
            opener=os.open,
            fstat=lambda _fd: metadata,
            reader=os.read,
            closer=os.close,
            unlink=os.unlink,
        )

    def _temporary_spec(self, template, contents: bytes):
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / template.path.name
        path.write_bytes(contents)
        return directory, replace(template, path=path)

    def _exercise_public_rollback(
        self,
        *,
        invalid_path: Path | None = None,
        invalid_case: str | None = None,
        missing_path: Path | None = None,
    ):
        specs = tuple(
            replace(template, path=Path("/rollback-fixture") / template.path.as_posix().lstrip("/"))
            for template in self.installer.runtime_file_specs()
        )
        members = {spec.path for spec in specs}
        if missing_path is not None:
            members.remove(missing_path)
        metadata = {
            spec.path: SimpleNamespace(
                st_mode=stat.S_IFREG | spec.mode,
                st_uid=0,
                st_gid=0,
                st_size=0,
                st_dev=1,
                st_ino=index,
            )
            for index, spec in enumerate(specs, start=1)
        }
        events: list[tuple[str, Path]] = []

        def validate(spec, **_kwargs):
            events.append(("validate", spec.path))
            if spec.path not in members:
                raise FileNotFoundError(spec.path)
            if spec.path == invalid_path:
                if invalid_case is not None:
                    invalid_metadata = SimpleNamespace(**vars(metadata[spec.path]))
                    if invalid_case == "mode":
                        invalid_metadata.st_mode = stat.S_IFREG | (spec.mode ^ 0o100)
                    elif invalid_case == "owner":
                        invalid_metadata.st_uid = 1001
                    elif invalid_case == "type":
                        invalid_metadata.st_mode = stat.S_IFLNK | spec.mode
                    else:
                        self.fail(f"unknown invalid fixture case: {invalid_case}")
                    self.installer._validate_runtime_metadata(invalid_metadata, spec)
                raise self.installer.InstallError("fixture runtime target is invalid")
            return metadata[spec.path]

        def lstat(path: Path):
            if path not in members:
                raise FileNotFoundError(path)
            return metadata[path]

        def unlink(path: Path) -> None:
            events.append(("unlink", path))
            members.remove(path)

        with (
            mock.patch.object(self.installer, "runtime_file_specs", return_value=specs),
            mock.patch.object(self.installer, "validate_install_preflight"),
            mock.patch.object(self.installer, "_validate_runtime_file", side_effect=validate),
            mock.patch.object(self.installer.os, "geteuid", return_value=0),
            mock.patch.object(self.installer.os, "lstat", side_effect=lstat),
            mock.patch.object(self.installer.os, "unlink", side_effect=unlink),
        ):
            try:
                self.installer.rollback()
                failure = None
            except Exception as exc:  # the contract deliberately exposes refusal
                failure = exc
        return specs, members, events, failure

    def _exercise_install_cleanup(self, *, invalid_path: Path | None = None):
        specs = tuple(
            replace(template, path=Path("/cleanup-fixture") / template.path.name)
            for template in self.installer.runtime_file_specs()[:2]
        )
        unrelated = replace(
            self.installer.RUNTIME_AUDIT_LOG_SPEC,
            path=Path("/cleanup-fixture/unrelated-audit.log"),
        )
        members = {*(spec.path for spec in specs), unrelated.path}
        metadata = {
            path: SimpleNamespace(
                st_mode=stat.S_IFREG | (next(spec.mode for spec in specs if spec.path == path) if path != unrelated.path else unrelated.mode),
                st_uid=0,
                st_gid=0,
                st_size=0,
                st_dev=1,
                st_ino=index,
            )
            for index, path in enumerate(members, start=1)
        }
        events: list[tuple[str, Path]] = []

        def validate(spec):
            events.append(("validate", spec.path))
            if spec.path == invalid_path:
                raise self.installer.InstallError("published runtime target was modified")
            return metadata[spec.path]

        def lstat(path: Path):
            if path not in members:
                raise FileNotFoundError(path)
            return metadata[path]

        def unlink(path: Path) -> None:
            events.append(("unlink", path))
            members.remove(path)

        try:
            self.installer._cleanup_published_runtime_files(
                specs,
                validate=validate,
                lstat=lstat,
                unlink=unlink,
            )
            failure = None
        except Exception as exc:
            failure = exc
        return specs, unrelated, members, events, failure

    def test_public_rollback_deletes_all_four_only_after_complete_pristine_preflight(self) -> None:
        specs, members, events, failure = self._exercise_public_rollback()
        self.assertIsNone(failure)
        self.assertEqual(members, set())
        self.assertEqual([path for operation, path in events if operation == "unlink"], [spec.path for spec in specs])
        self.assertEqual(events[:4], [("validate", spec.path) for spec in specs])
        self.assertGreater(events.index(("unlink", specs[0].path)), 3)

    def test_preflighted_deletion_stops_when_identity_changes_before_unlink(self) -> None:
        specs = tuple(
            replace(template, path=Path("/identity-fixture") / str(index) / template.path.name)
            for index, template in enumerate(self.installer.runtime_file_specs(), start=1)
        )
        metadata = {
            spec.path: SimpleNamespace(
                st_mode=stat.S_IFREG | spec.mode,
                st_uid=0,
                st_gid=0,
                st_size=0,
                st_dev=1,
                st_ino=index,
            )
            for index, spec in enumerate(specs, start=1)
        }
        changed = SimpleNamespace(**vars(metadata[specs[1].path]))
        changed.st_ino = 99
        unlinked: list[Path] = []

        def validate(spec):
            return changed if spec.path == specs[1].path else metadata[spec.path]

        with self.assertRaises(self.installer.InstallError):
            self.installer._delete_validated_runtime_files(
                tuple((spec, metadata[spec.path]) for spec in specs),
                validate=validate,
                lstat=lambda path: metadata[path],
                unlink=unlinked.append,
            )
        self.assertEqual(unlinked, [specs[0].path])
        self.assertNotIn(specs[2].path, unlinked)
        self.assertNotIn(specs[3].path, unlinked)

    def test_public_rollback_nonempty_audit_blocks_every_deletion(self) -> None:
        audit_path = Path("/rollback-fixture") / self.installer.RUNTIME_AUDIT_LOG_PATH.as_posix().lstrip("/")
        specs, members, events, failure = self._exercise_public_rollback(invalid_path=audit_path)
        self.assertIsInstance(failure, self.installer.InstallError)
        self.assertEqual(members, {spec.path for spec in specs})
        self.assertEqual([event for event in events if event[0] == "unlink"], [])

    def test_public_rollback_wrong_content_for_each_blob_member_blocks_every_deletion(self) -> None:
        for template in (
            self.installer.RUNTIME_LAUNCHER_SPEC,
            self.installer.RUNTIME_VERIFIER_SPEC,
            self.installer.RUNTIME_SUDOERS_SPEC,
        ):
            with self.subTest(path=template.path):
                invalid_path = Path("/rollback-fixture") / template.path.as_posix().lstrip("/")
                specs, members, events, failure = self._exercise_public_rollback(invalid_path=invalid_path)
                self.assertIsInstance(failure, self.installer.InstallError)
                self.assertEqual(members, {spec.path for spec in specs})
                self.assertEqual([event for event in events if event[0] == "unlink"], [])

    def test_public_rollback_invalid_mode_owner_or_type_of_any_member_blocks_every_deletion(self) -> None:
        for invalid_case in ("mode", "owner", "type"):
            for template in self.installer.runtime_file_specs():
                with self.subTest(case=invalid_case, path=template.path):
                    invalid_path = Path("/rollback-fixture") / template.path.as_posix().lstrip("/")
                    specs, members, events, failure = self._exercise_public_rollback(
                        invalid_path=invalid_path,
                        invalid_case=invalid_case,
                    )
                    self.assertIsInstance(failure, self.installer.InstallError)
                    self.assertEqual(members, {spec.path for spec in specs})
                    self.assertEqual([event for event in events if event[0] == "unlink"], [])

    def test_public_rollback_missing_any_member_blocks_every_deletion(self) -> None:
        for template in self.installer.runtime_file_specs():
            with self.subTest(path=template.path):
                missing_path = Path("/rollback-fixture") / template.path.as_posix().lstrip("/")
                specs, members, events, failure = self._exercise_public_rollback(missing_path=missing_path)
                self.assertIsInstance(failure, self.installer.InstallError)
                self.assertEqual(members, {spec.path for spec in specs if spec.path != missing_path})
                self.assertEqual([event for event in events if event[0] == "unlink"], [])

    def test_install_cleanup_prevalidates_current_invocation_set_then_deletes_in_reverse_order(self) -> None:
        specs, unrelated, members, events, failure = self._exercise_install_cleanup()
        self.assertIsNone(failure)
        self.assertEqual(members, {unrelated.path})
        self.assertEqual([path for operation, path in events if operation == "unlink"], list(reversed([spec.path for spec in specs])))
        self.assertEqual(events[:2], [("validate", spec.path) for spec in specs])
        self.assertGreater(events.index(("unlink", specs[-1].path)), 1)

    def test_install_cleanup_modified_member_deletes_none_and_preserves_unrelated_fixture(self) -> None:
        invalid_path = Path("/cleanup-fixture") / self.installer.RUNTIME_VERIFIER_PATH.name
        specs, unrelated, members, events, failure = self._exercise_install_cleanup(invalid_path=invalid_path)
        self.assertIsInstance(failure, self.installer.InstallError)
        self.assertEqual(members, {*(spec.path for spec in specs), unrelated.path})
        self.assertEqual([event for event in events if event[0] == "unlink"], [])

    def test_exact_launcher_identity_is_accepted_for_deletion(self) -> None:
        directory, spec = self._temporary_spec(
            self.installer.RUNTIME_LAUNCHER_SPEC, LAUNCHER_PATH.read_bytes()
        )
        try:
            self._safe_delete(spec)
            self.assertFalse(spec.path.exists())
        finally:
            directory.cleanup()

    def test_wrong_runtime_blobs_and_non_empty_audit_are_rejected_before_deletion(self) -> None:
        cases = (
            (self.installer.RUNTIME_LAUNCHER_SPEC, b"wrong launcher"),
            (self.installer.RUNTIME_VERIFIER_SPEC, b"wrong verifier"),
            (self.installer.RUNTIME_SUDOERS_SPEC, b"wrong sudoers"),
            (self.installer.RUNTIME_AUDIT_LOG_SPEC, b"audit evidence"),
        )
        for template, contents in cases:
            with self.subTest(path=template.path):
                directory, spec = self._temporary_spec(template, contents)
                try:
                    with self.assertRaises(self.installer.InstallError):
                        self._safe_delete(spec)
                    self.assertTrue(spec.path.exists())
                finally:
                    directory.cleanup()

    def test_wrong_mode_owner_group_symlink_directory_and_non_regular_are_rejected(self) -> None:
        directory, spec = self._temporary_spec(
            self.installer.RUNTIME_LAUNCHER_SPEC, LAUNCHER_PATH.read_bytes()
        )
        try:
            invalid_metadata = (
                self._root_file_metadata(spec.path, mode=0o600),
                self._root_file_metadata(spec.path, mode=spec.mode, uid=1001),
                self._root_file_metadata(spec.path, mode=spec.mode, gid=1001),
                self._root_file_metadata(spec.path, mode=spec.mode, file_type=stat.S_IFLNK),
                self._root_file_metadata(spec.path, mode=spec.mode, file_type=stat.S_IFDIR),
                self._root_file_metadata(spec.path, mode=spec.mode, file_type=stat.S_IFIFO),
            )
            for metadata in invalid_metadata:
                with self.subTest(mode=metadata.st_mode, uid=metadata.st_uid, gid=metadata.st_gid):
                    with self.assertRaises(self.installer.InstallError):
                        self._safe_delete(spec, metadata=metadata)
                    self.assertTrue(spec.path.exists())
        finally:
            directory.cleanup()


    def _directory_metadata(self, *, mode: int = 0o700, uid: int = 0, gid: int = 0):
        return SimpleNamespace(st_mode=stat.S_IFDIR | mode, st_uid=uid, st_gid=gid)

    def test_system_parents_are_preexisting_only_and_never_repermissioned(self) -> None:
        installer = self.installer
        records = {path: self._directory_metadata() for path in installer.SYSTEM_PARENT_DIRECTORIES}
        missing = Path("/usr/local/lib")
        records.pop(missing)
        created: list[Path] = []
        mkdir_calls: list[Path] = []
        with self.assertRaises(installer.InstallError):
            installer._ensure_runtime_parent(
                installer.RUNTIME_VERIFIER_PATH,
                created,
                lstat=lambda path: records[path] if path in records else (_ for _ in ()).throw(FileNotFoundError(path)),
                mkdir=lambda path, mode: mkdir_calls.append(path),
            )
        self.assertEqual(mkdir_calls, [])
        self.assertEqual(created, [])

    def test_only_allowlisted_support_directories_are_created_and_valid_existing_are_preserved(self) -> None:
        installer = self.installer
        records = {path: self._directory_metadata() for path in installer.SYSTEM_PARENT_DIRECTORIES}
        created: list[Path] = []
        mkdir_calls: list[tuple[Path, int]] = []

        def lstat(path: Path):
            if path not in records:
                raise FileNotFoundError(path)
            return records[path]

        def mkdir(path: Path, mode: int) -> None:
            mkdir_calls.append((path, mode))
            records[path] = self._directory_metadata(mode=mode)

        installer._ensure_runtime_parent(installer.RUNTIME_VERIFIER_PATH, created, lstat=lstat, mkdir=mkdir)
        self.assertEqual(created, list(installer.VERIFIER_SUPPORT_DIRECTORIES))
        self.assertEqual(mkdir_calls, [(path, 0o700) for path in installer.VERIFIER_SUPPORT_DIRECTORIES])
        installer._ensure_runtime_parent(installer.RUNTIME_VERIFIER_PATH, created, lstat=lstat, mkdir=mkdir)
        self.assertEqual(mkdir_calls, [(path, 0o700) for path in installer.VERIFIER_SUPPORT_DIRECTORIES])

    def test_invalid_existing_support_directory_fails_closed(self) -> None:
        installer = self.installer
        records = {path: self._directory_metadata() for path in installer.SYSTEM_PARENT_DIRECTORIES}
        records[installer.VERIFIER_SUPPORT_DIRECTORIES[0]] = self._directory_metadata(mode=0o770)
        with self.assertRaises(installer.InstallError):
            installer._ensure_runtime_parent(
                installer.RUNTIME_VERIFIER_PATH,
                [],
                lstat=lambda path: records[path],
                mkdir=lambda _path, _mode: self.fail("invalid directory must not be recreated"),
            )

    def test_created_support_directory_cleanup_is_bounded_and_preserves_preexisting(self) -> None:
        installer = self.installer
        created = list(installer.VERIFIER_SUPPORT_DIRECTORIES)
        records = {path: self._directory_metadata() for path in created}
        removed: list[Path] = []
        installer._cleanup_created_support_directories(
            created,
            lstat=lambda path: records[path],
            listdir=lambda _path: [],
            rmdir=lambda path: removed.append(path),
        )
        self.assertEqual(removed, list(reversed(created)))
        self.assertTrue(set(removed).issubset(installer.DEDICATED_SUPPORT_DIRECTORIES))
        self.assertTrue(set(installer.rollback_paths()).isdisjoint(installer.DEDICATED_SUPPORT_DIRECTORIES))

    def test_created_support_directory_cleanup_refuses_invalid_or_nonempty_directories(self) -> None:
        installer = self.installer
        target = installer.AUDIT_SUPPORT_DIRECTORIES[0]
        removed: list[Path] = []
        for metadata, entries in ((self._directory_metadata(mode=0o755), []), (self._directory_metadata(), ["evidence"])):
            with self.subTest(mode=metadata.st_mode, entries=entries):
                installer._cleanup_created_support_directories(
                    [target],
                    lstat=lambda _path, value=metadata: value,
                    listdir=lambda _path, value=entries: value,
                    rmdir=lambda path: removed.append(path),
                )
        self.assertEqual(removed, [])


if __name__ == "__main__":
    unittest.main()
