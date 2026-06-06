from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base import GenerationRequest, GenerationResult


def _load_env_key_if_missing(key: str) -> None:
    if os.environ.get(key, "").strip():
        return

    for parent in Path(__file__).resolve().parents:
        env_path = parent / ".env"
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            name, value = stripped.split("=", 1)
            if name.strip() != key:
                continue
            cleaned = value.strip().strip('"').strip("'")
            if cleaned:
                os.environ[key] = cleaned
            return


class ToioToProvider:
    name = "toioto"
    api_key_env = "TOIOTO_API_KEY"
    endpoint_env = "TOIOTO_IMAGE_ENDPOINT"
    edit_endpoint_env = "TOIOTO_IMAGE_EDIT_ENDPOINT"
    default_endpoint = "https://sub2api.toioto.org/v1/images/generations"
    default_edit_endpoint = "https://sub2api.toioto.org/v1/images/edits"
    default_model = "gpt-image-2"

    def is_configured(self) -> bool:
        _load_env_key_if_missing(self.api_key_env)
        return bool(os.environ.get(self.api_key_env, "").strip())

    def configuration_message(self) -> str:
        if self.is_configured():
            return "ToioTo 生图已配置。"
        return f"设置 {self.api_key_env} 后可启用 ToioTo 生图。"

    def _endpoint(self) -> str:
        return os.environ.get(self.endpoint_env, "").strip() or self.default_endpoint

    def _edit_endpoint(self) -> str:
        return os.environ.get(self.edit_endpoint_env, "").strip() or self.default_edit_endpoint

    def _build_prompt(self, request: GenerationRequest) -> str:
        parts: list[str] = []
        if request.style_text.strip():
            parts.append(f"Style reference:\n{request.style_text.strip()}")
        parts.append(request.prompt.strip())
        if request.negative_prompt.strip():
            parts.append(f"Avoid:\n{request.negative_prompt.strip()}")
        return "\n\n".join(parts).strip()

    def _build_payload(self, request: GenerationRequest) -> dict:
        quality = str(request.params.get("quality") or "low").strip() or "low"
        payload = {
            "model": str(request.params.get("model") or self.default_model),
            "prompt": self._build_prompt(request),
            "size": f"{request.width}x{request.height}",
            "quality": quality,
            "n": request.count,
            "output_format": "png",
        }
        if request.transparent_background:
            payload["background"] = "transparent"
        return payload

    def _build_multipart_body(
        self,
        fields: dict[str, object],
        files: list[tuple[str, Path]],
    ) -> tuple[bytes, str]:
        boundary = f"----SpriteVideoLab{uuid.uuid4().hex}"
        chunks: list[bytes] = []
        for name, value in fields.items():
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode("utf-8"),
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                    f"{value}\r\n".encode("utf-8"),
                ]
            )
        for name, path in files:
            filename = path.name
            content_type = "image/png" if path.suffix.lower() == ".png" else "application/octet-stream"
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode("utf-8"),
                    (
                        f'Content-Disposition: form-data; name="{name}"; '
                        f'filename="{filename}"\r\n'
                    ).encode("utf-8"),
                    f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
                    path.read_bytes(),
                    b"\r\n",
                ]
            )
        chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
        return b"".join(chunks), boundary

    def _post_json(self, endpoint: str, payload: dict) -> bytes:
        curl_path = shutil.which("curl.exe") or shutil.which("curl")
        if curl_path:
            return self._post_json_with_curl(curl_path, endpoint, payload)

        http_request = Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {os.environ[self.api_key_env]}",
                "Content-Type": "application/json",
            },
        )
        return self._send_request(http_request)

    def _post_json_with_curl(self, curl_path: str, endpoint: str, payload: dict) -> bytes:
        with TemporaryDirectory(prefix="sprite-video-lab-toioto-") as temp_dir_raw:
            temp_dir = Path(temp_dir_raw)
            request_path = temp_dir / "request.json"
            response_path = temp_dir / "response.json"
            request_path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    curl_path,
                    "-sS",
                    "-o",
                    str(response_path),
                    "-X",
                    "POST",
                    endpoint,
                    "-H",
                    f"Authorization: Bearer {os.environ[self.api_key_env]}",
                    "-H",
                    "Content-Type: application/json",
                    "--data-binary",
                    f"@{request_path}",
                    "--max-time",
                    "180",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            response_body = response_path.read_bytes() if response_path.exists() else b""
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or response_body.decode("utf-8", errors="replace")).strip()
                raise RuntimeError(f"ToioTo 生图请求失败：curl 退出码 {completed.returncode} {detail}")
            return response_body

    def _post_multipart(
        self,
        endpoint: str,
        fields: dict[str, object],
        files: list[tuple[str, Path]],
    ) -> bytes:
        curl_path = shutil.which("curl.exe") or shutil.which("curl")
        if curl_path:
            return self._post_multipart_with_curl(curl_path, endpoint, fields, files)

        body, boundary = self._build_multipart_body(fields, files)
        http_request = Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {os.environ[self.api_key_env]}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        return self._send_request(http_request)

    def _post_multipart_with_curl(
        self,
        curl_path: str,
        endpoint: str,
        fields: dict[str, object],
        files: list[tuple[str, Path]],
    ) -> bytes:
        with TemporaryDirectory(prefix="sprite-video-lab-toioto-") as temp_dir_raw:
            response_path = Path(temp_dir_raw) / "response.json"
            args = [
                curl_path,
                "-sS",
                "-o",
                str(response_path),
                "-X",
                "POST",
                endpoint,
                "-H",
                f"Authorization: Bearer {os.environ[self.api_key_env]}",
                "--max-time",
                "180",
            ]
            for name, value in fields.items():
                args.extend(["-F", f"{name}={value}"])
            for name, path in files:
                args.extend(["-F", f"{name}=@{path}"])
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            response_body = response_path.read_bytes() if response_path.exists() else b""
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or response_body.decode("utf-8", errors="replace")).strip()
                raise RuntimeError(f"ToioTo 生图请求失败：curl 退出码 {completed.returncode} {detail}")
            return response_body

    def _send_request(self, http_request: Request) -> bytes:
        try:
            with urlopen(http_request, timeout=180) as response:
                return response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"ToioTo 生图请求失败：HTTP {exc.code} {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"ToioTo 生图请求失败：{exc.reason}") from exc

    def _save_response_images(self, response_body: bytes, output_dir: Path) -> list[Path]:
        data = json.loads(response_body.decode("utf-8"))
        if data.get("error"):
            error = data["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            code = error.get("code", "") if isinstance(error, dict) else ""
            raise RuntimeError(f"ToioTo 生图请求失败：{message or code or '未知错误'}")
        if data.get("message") or data.get("code"):
            message = str(data.get("message") or data.get("code") or "未知错误")
            code = str(data.get("code") or "")
            suffix = f" ({code})" if code and code not in message else ""
            raise RuntimeError(f"ToioTo 生图请求失败：{message}{suffix}")
        image_paths: list[Path] = []
        for index, item in enumerate(data.get("data") or []):
            b64_json = item.get("b64_json")
            if not b64_json:
                continue
            image_path = output_dir / f"toioto_{index + 1:02d}.png"
            image_path.write_bytes(base64.b64decode(b64_json))
            image_paths.append(image_path)
        if not image_paths:
            raise RuntimeError("ToioTo 返回结果中没有可保存的图片。")
        return image_paths

    def generate(
        self,
        request: GenerationRequest,
        output_dir: Path,
    ) -> GenerationResult:
        if not self.is_configured():
            raise RuntimeError(self.configuration_message())

        output_dir.mkdir(parents=True, exist_ok=True)
        payload = self._build_payload(request)
        mode = "reference" if request.reference_image_paths else "text"
        endpoint = self._endpoint()
        if request.reference_image_paths:
            endpoint = self._edit_endpoint()
            fields = {key: value for key, value in payload.items() if key != "background"}
            files = [("image", path) for path in request.reference_image_paths]
            if request.mask_image_path is not None:
                files.append(("mask", request.mask_image_path))
            response_body = self._post_multipart(endpoint, fields, files)
        else:
            response_body = self._post_json(endpoint, payload)

        image_paths = self._save_response_images(response_body, output_dir)

        provider_params = {
            key: value
            for key, value in payload.items()
            if key != "prompt"
        }
        provider_params["endpoint"] = endpoint
        provider_params["mode"] = mode
        if request.reference_image_paths:
            provider_params["reference_image_count"] = len(request.reference_image_paths)
        if request.mask_image_path is not None:
            provider_params["has_mask"] = True
        return GenerationResult(
            image_paths=image_paths,
            provider_params=provider_params,
        )
