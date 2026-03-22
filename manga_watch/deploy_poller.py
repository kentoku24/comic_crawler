from pathlib import Path


def load_deploy_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()

    if not values.get("COMIC_CRAWLER_IMAGE_REF"):
        raise ValueError("deploy env must define COMIC_CRAWLER_IMAGE_REF")
    return values


def render_updated_deploy_env(existing_text: str, image_ref: str) -> str:
    rendered: list[str] = []
    replaced = False

    for line in existing_text.splitlines():
        key, separator, _ = line.partition("=")
        if separator and key.strip() == "COMIC_CRAWLER_IMAGE_REF":
            rendered.append(f"COMIC_CRAWLER_IMAGE_REF={image_ref}")
            replaced = True
            continue
        rendered.append(line)

    if not replaced:
        rendered.append(f"COMIC_CRAWLER_IMAGE_REF={image_ref}")

    return "\n".join(rendered) + "\n"
