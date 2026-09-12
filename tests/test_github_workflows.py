import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - CI has no PyYAML
    yaml = None
    _HAS_YAML = False
else:
    _HAS_YAML = True


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def read_workflow(name: str) -> str:
    workflow_path = repo_root() / ".github" / "workflows" / name
    if not workflow_path.exists():
        raise AssertionError(f"missing workflow: {workflow_path}")
    return workflow_path.read_text(encoding="utf-8")


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _is_blank_or_comment(line: str) -> bool:
    stripped = line.strip()
    return stripped == "" or stripped == "---" or stripped.startswith("#")


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _split_key_value(text: str):
    """Split 'key: value' on the first colon that ends the key.

    Returns (key, value) or None when the colon is not a mapping colon
    (e.g. 'https://...' inside a scalar).
    """
    head, sep, tail = text.partition(":")
    if not sep:
        return None
    if tail != "" and not tail.startswith(" "):
        return None
    return head.strip(), tail.strip()


def _mini_yaml_load(text: str):
    """Minimal stdlib YAML-subset parser for the production workflows.

    Handles nested mappings, '- ' sequences (incl. '- key: value' maps),
    'key: |' literal blocks and quoted scalars. Anything else (anchors,
    flow collections, multi-line quotes) is out of scope on purpose:
    the workflows under test do not use them.
    """

    lines = text.splitlines()
    total = len(lines)

    def parse_node(i: int, indent: int):
        while i < total and _is_blank_or_comment(lines[i]):
            i += 1
        if i >= total or _indent_of(lines[i]) < indent:
            return None, i
        stripped = lines[i].lstrip(" ")
        if stripped.startswith("- ") or stripped == "-":
            return parse_list(i, indent)
        return parse_map(i, indent)

    def parse_map(i: int, indent: int):
        mapping = {}
        while True:
            while i < total and _is_blank_or_comment(lines[i]):
                i += 1
            if i >= total or _indent_of(lines[i]) != indent:
                break
            stripped = lines[i].lstrip(" ")
            if stripped.startswith("- ") or stripped == "-":
                break
            split = _split_key_value(stripped)
            if split is None:
                i += 1
                continue
            key, rest = split
            key = _strip_quotes(key)
            i += 1
            if rest == "|":
                block = []
                while i < total and (
                    lines[i].strip() == "" or _indent_of(lines[i]) > indent
                ):
                    if lines[i].strip() != "":
                        block.append(lines[i])
                    i += 1
                if block:
                    dedent = min(_indent_of(line) for line in block)
                    block = [line[dedent:] for line in block]
                mapping[key] = "\n".join(block) + ("\n" if block else "")
            elif rest == "":
                probe = i
                while probe < total and _is_blank_or_comment(lines[probe]):
                    probe += 1
                if probe < total and _indent_of(lines[probe]) > indent:
                    child, i = parse_node(probe, _indent_of(lines[probe]))
                    mapping[key] = child
                else:
                    mapping[key] = None
            else:
                mapping[key] = _strip_quotes(rest)
        return mapping, i

    def parse_list(i: int, indent: int):
        items = []
        while True:
            while i < total and _is_blank_or_comment(lines[i]):
                i += 1
            if i >= total or _indent_of(lines[i]) != indent:
                break
            stripped = lines[i].lstrip(" ")
            if not (stripped.startswith("- ") or stripped == "-"):
                break
            after = stripped[1:].strip()
            i += 1
            if after == "":
                probe = i
                while probe < total and _is_blank_or_comment(lines[probe]):
                    probe += 1
                if probe < total and _indent_of(lines[probe]) > indent:
                    child, i = parse_node(probe, _indent_of(lines[probe]))
                    items.append(child)
                else:
                    items.append(None)
                continue
            split = _split_key_value(after)
            if split is None:
                items.append(_strip_quotes(after))
                continue
            key, rest = split
            item = {_strip_quotes(key): _strip_quotes(rest)}
            probe = i
            while probe < total and _is_blank_or_comment(lines[probe]):
                probe += 1
            if probe < total and _indent_of(lines[probe]) > indent:
                extra, i = parse_map(probe, _indent_of(lines[probe]))
                item.update(extra)
            items.append(item)
        return items, i

    doc, _ = parse_node(0, 0)
    return doc


def load_workflow(name: str):
    """Parse a workflow file, preferring yaml.safe_load.

    PyYAML is not in requirements.txt (and therefore not in CI), so fall
    back to the stdlib subset parser instead of adding a dependency.
    """
    text = read_workflow(name)
    try:
        import yaml
    except ImportError:
        doc = _mini_yaml_load(text)
    else:
        doc = yaml.safe_load(text)
    if isinstance(doc, dict) and "on" not in doc and True in doc:
        # YAML 1.1 parses the 'on:' key as boolean True.
        doc["on"] = doc.pop(True)
    return doc


def job_steps(job: dict) -> list:
    steps = job.get("steps") or []
    if not isinstance(steps, list):
        raise AssertionError(f"job steps must be a list, got: {steps!r}")
    return steps


def step_run_texts(steps: list) -> list:
    return [step.get("run") or "" for step in steps if isinstance(step, dict)]


def _normalize_for_parity(value):
    """Normalize scalar typing so stdlib strings compare with typed YAML.

    _mini_yaml_load keeps every scalar a string while yaml.safe_load
    coerces ints/bools; structural drift (not scalar typing) is what
    this parity guard watches, so bools/numbers stringify here.
    """
    if isinstance(value, bool):
        return str(value).lower()
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        normalized = {}
        for key, item in value.items():
            if key is True:
                key = "on"
            normalized[str(key)] = _normalize_for_parity(item)
        return normalized
    if isinstance(value, list):
        return [_normalize_for_parity(item) for item in value]
    return value


class GitHubWorkflowContractTests(unittest.TestCase):
    def test_deploy_workflow_exists_and_targets_main_push(self):
        doc = load_workflow("deploy-production.yml")

        branches = doc["on"]["push"]["branches"]
        self.assertIn("main", branches)

    def test_deploy_workflow_defines_test_build_and_deploy_jobs(self):
        doc = load_workflow("deploy-production.yml")

        jobs = doc["jobs"]
        for expected in ("test", "build", "deploy"):
            self.assertIn(expected, jobs)
        self.assertEqual("production", jobs["deploy"].get("environment"))

    def test_deploy_workflow_emits_and_consumes_an_image_digest(self):
        doc = load_workflow("deploy-production.yml")

        build_outputs = doc["jobs"]["build"].get("outputs") or {}
        self.assertIn("image_digest", build_outputs)
        self.assertIn("image_ref", build_outputs)

        deploy_env = doc["jobs"]["deploy"].get("env") or {}
        self.assertIn("IMAGE_REF", deploy_env)
        self.assertIn("IMAGE_DIGEST", deploy_env)
        self.assertIn("needs.build.outputs.image_ref", str(deploy_env["IMAGE_REF"]))
        self.assertIn(
            "needs.build.outputs.image_digest", str(deploy_env["IMAGE_DIGEST"])
        )

    def test_deploy_workflow_verifies_service_and_job_image_refs_from_resource_configs(self):
        doc = load_workflow("deploy-production.yml")

        runs = step_run_texts(job_steps(doc["jobs"]["deploy"]))
        service_runs = [
            run
            for run in runs
            if "value(spec.template.spec.containers[0].image)" in run
        ]
        job_runs = [
            run
            for run in runs
            if "value(spec.template.spec.template.spec.containers[0].image)"
            in run
        ]
        self.assertTrue(
            service_runs, "no deploy step verifies the service image-ref"
        )
        self.assertTrue(job_runs, "no deploy step verifies the job image-ref")
        self.assertTrue(
            any('if [[ "${service_image_ref}" != "${IMAGE_REF}" ]]' in run for run in runs),
            "no deploy step guards on the service image-ref mismatch",
        )
        self.assertTrue(
            any('if [[ "${job_image_ref}" != "${IMAGE_REF}" ]]' in run for run in runs),
            "no deploy step guards on the job image-ref mismatch",
        )

    def test_deploy_workflow_sets_up_buildx_before_using_gha_cache(self):
        doc = load_workflow("deploy-production.yml")

        steps = job_steps(doc["jobs"]["build"])
        uses = [step.get("uses") or "" for step in steps if isinstance(step, dict)]
        buildx_index = next(
            i for i, entry in enumerate(uses) if "docker/setup-buildx-action" in entry
        )
        build_index = next(
            i for i, entry in enumerate(uses) if "docker/build-push-action" in entry
        )
        self.assertLess(buildx_index, build_index)

        buildx_step = steps[buildx_index]
        self.assertIn("docker-container", str((buildx_step.get("with") or {}).get("driver")))

        build_with = steps[build_index].get("with") or {}
        self.assertIn("cache-from", build_with)
        self.assertIn("cache-to", build_with)
        self.assertIn("type=gha", str(build_with["cache-from"]))
        self.assertIn("type=gha,mode=max", str(build_with["cache-to"]))

    def test_rollback_workflow_exists_and_uses_workflow_dispatch(self):
        doc = load_workflow("rollback-production.yml")

        inputs = doc["on"]["workflow_dispatch"]["inputs"]
        self.assertIn("image_ref", inputs)
        self.assertEqual("string", inputs["image_ref"].get("type"))

    def test_rollback_workflow_defines_validate_and_rollback_jobs(self):
        doc = load_workflow("rollback-production.yml")

        jobs = doc["jobs"]
        for expected in ("validate", "rollback"):
            self.assertIn(expected, jobs)
        self.assertEqual("production", jobs["rollback"].get("environment"))

    def test_rollback_workflow_validates_input_without_gcp_auth_and_updates_both_resources_after_gate(self):
        doc = load_workflow("rollback-production.yml")

        validate_steps = job_steps(doc["jobs"]["validate"])
        for step in validate_steps:
            uses = step.get("uses") or ""
            name = step.get("name") or ""
            run = step.get("run") or ""
            self.assertNotIn("google-github-actions/auth", uses)
            self.assertNotIn("Authenticate to Google Cloud", name)
            self.assertNotIn("gcloud artifacts docker images describe", run)

        runs = step_run_texts(job_steps(doc["jobs"]["rollback"]))
        self.assertTrue(
            any("gcloud artifacts docker images describe" in run for run in runs),
            "no rollback step describes the rollback target in Artifact Registry",
        )
        self.assertTrue(
            any("gcloud run jobs update comic-crawler-job" in run for run in runs),
            "no rollback step updates the Cloud Run Job resource",
        )
        self.assertTrue(
            any("gcloud run deploy comic-crawler-service" in run for run in runs),
            "no rollback step updates the Cloud Run Service resource",
        )

    @unittest.skipUnless(_HAS_YAML, "PyYAML not installed; parity needs yaml.safe_load")
    def test_mini_yaml_load_matches_pyyaml_on_target_keys(self):
        for name in ("deploy-production.yml", "rollback-production.yml"):
            text = read_workflow(name)
            expected = yaml.safe_load(text)
            if isinstance(expected, dict) and "on" not in expected and True in expected:
                expected["on"] = expected.pop(True)
            actual = _mini_yaml_load(text)
            for key in ("on", "jobs"):
                self.assertEqual(
                    _normalize_for_parity(actual.get(key)),
                    _normalize_for_parity(expected.get(key)),
                    f"{name}:{key} drift between _mini_yaml_load and yaml.safe_load",
                )


if __name__ == "__main__":
    unittest.main()
