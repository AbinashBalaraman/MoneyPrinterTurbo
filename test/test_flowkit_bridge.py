"""Tests for the flowkit -> AutoShorts image bridge.

No network and no flowkit process: the HTTP session is faked, and images are
real files written with Pillow so the format-normalisation and resolution
checks exercise the same code the live path would.

The last test deliberately validates the material dict against the real
``MaterialInfo`` model. If ``app/models/schema.py`` ever changes shape, that
test fails here rather than at task 1 of an unattended batch.
"""

import io
from pathlib import Path

import pytest
from PIL import Image

from automation.flowkit_bridge import (
    ACCEPTED_IMAGE_EXTS,
    MIN_MATERIAL_DIMENSION,
    FlowkitError,
    FlowkitImageSource,
    ImageAsset,
    StagedImage,
    _normalise_image,
    _slugify,
    apply_to_params,
    stage_flowkit_images,
)

FLOWKIT_URL = "http://127.0.0.1:8100"
PROJECT_ID = "f5ce611c-3f4c-471d-8dcf-c26059defa3f"


def make_image_bytes(width=1024, height=1820, fmt="PNG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (30, 90, 140)).save(buffer, format=fmt)
    return buffer.getvalue()


class FakeResponse:
    """Mimics the slice of ``requests.Response`` the bridge touches."""

    def __init__(self, status_code=200, json_data=None, content=b"", text=""):
        self.status_code = status_code
        self._json = json_data
        self._content = content
        self.text = text or ""

    def json(self):
        if self._json is None:
            raise ValueError("no JSON body")
        return self._json

    def iter_content(self, chunk_size=65536):
        for start in range(0, len(self._content), chunk_size):
            yield self._content[start : start + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class FakeSession:
    """Routes GET/POST by substring, so tests read as intent not plumbing."""

    def __init__(self, get_routes=None, post_routes=None):
        self.get_routes = get_routes or {}
        self.post_routes = post_routes or {}
        self.get_calls = []
        self.post_calls = []

    def _route(self, routes, url):
        for fragment, response in routes.items():
            if fragment in url:
                return response() if callable(response) else response
        raise AssertionError(f"unrouted URL: {url}")

    def get(self, url, timeout=None, stream=False):
        self.get_calls.append({"url": url, "timeout": timeout, "stream": stream})
        return self._route(self.get_routes, url)

    def post(self, url, json=None, timeout=None):
        self.post_calls.append({"url": url, "json": json, "timeout": timeout})
        return self._route(self.post_routes, url)

    def close(self):
        pass


def healthy_routes(**extra):
    routes = {
        "/health": FakeResponse(
            json_data={"status": "ok", "version": "0.2.0", "extension_connected": True}
        ),
        "/api/flow/status": FakeResponse(
            json_data={
                "connected": True,
                "transport": "batch",
                "flow_project_id": PROJECT_ID,
                "allow_degraded": False,
            }
        ),
    }
    routes.update(extra)
    return routes


def ready_client(get_routes=None, post_routes=None):
    return FlowkitImageSource(
        base_url=FLOWKIT_URL,
        session=FakeSession(get_routes=healthy_routes(**(get_routes or {})), post_routes=post_routes),
    )


# --- slugify ---------------------------------------------------------------


def test_slugify_lowercases_and_collapses_punctuation():
    assert _slugify("Arthur, the farmer!  Holding Rusty?") == "arthur_the_farmer_holding_rusty"


def test_slugify_is_bounded_and_never_empty():
    assert len(_slugify("x" * 200)) <= 40
    assert _slugify("") == "image"
    assert _slugify("!!!") == "image"


def test_slugify_does_not_end_with_separator():
    # A trailing underscore would produce "01_foo_.png" and read as a typo.
    assert not _slugify("hello world" + " " * 60).endswith("_")


# --- response parsing ------------------------------------------------------


def test_parse_media_reads_flowkit_generated_image_shape():
    payload = {
        "media": [
            {
                "name": "media-1",
                "image": {"generatedImage": {"mediaId": "media-1", "fifeUrl": "https://flow/img1.png"}},
            }
        ]
    }
    assets = FlowkitImageSource._parse_media(payload, "a barn at dawn")
    assert len(assets) == 1
    assert assets[0].media_id == "media-1"
    assert assets[0].url == "https://flow/img1.png"
    assert assets[0].prompt == "a barn at dawn"


def test_parse_media_accepts_bare_list():
    assets = FlowkitImageSource._parse_media(
        [{"image": {"generatedImage": {"mediaId": "m", "fifeUrl": "https://flow/x.png"}}}], "p"
    )
    assert assets[0].url == "https://flow/x.png"


def test_parse_media_raises_when_no_media():
    with pytest.raises(FlowkitError, match="returned no media"):
        FlowkitImageSource._parse_media({"media": []}, "p")


def test_parse_media_raises_when_record_has_no_url():
    # Better a clear error than a KeyError deep in the download step.
    with pytest.raises(FlowkitError, match="no image URL"):
        FlowkitImageSource._parse_media({"media": [{"image": {"generatedImage": {}}}]}, "p")


# --- readiness -------------------------------------------------------------


def test_require_ready_adopts_project_id_from_flowkit():
    client = ready_client()
    assert client.project_id == ""
    assert client.require_ready() == PROJECT_ID
    assert client.project_id == PROJECT_ID


def test_require_ready_prefers_configured_project_id():
    client = FlowkitImageSource(
        base_url=FLOWKIT_URL,
        project_id="configured-id",
        session=FakeSession(get_routes=healthy_routes()),
    )
    assert client.require_ready() == "configured-id"


def test_require_ready_raises_when_extension_disconnected():
    session = FakeSession(
        get_routes={
            "/health": FakeResponse(
                json_data={"status": "ok", "extension_connected": False}
            )
        }
    )
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=session)
    with pytest.raises(FlowkitError, match="extension is not connected"):
        client.require_ready()


def test_require_ready_raises_when_no_project_id_anywhere():
    session = FakeSession(
        get_routes={
            "/health": FakeResponse(json_data={"status": "ok", "extension_connected": True}),
            "/api/flow/status": FakeResponse(json_data={"connected": True, "flow_project_id": ""}),
        }
    )
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=session)
    with pytest.raises(FlowkitError, match="no Flow project id"):
        client.require_ready()


def test_unreachable_flowkit_gives_actionable_error():
    import requests

    class Boom(FakeSession):
        def get(self, url, timeout=None, stream=False):
            raise requests.ConnectionError("connection refused")

    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=Boom())
    with pytest.raises(FlowkitError, match="not reachable"):
        client.health()


# --- generate-image request ------------------------------------------------


def test_generate_image_sends_portrait_ratio_and_project_id():
    session = FakeSession(
        get_routes=healthy_routes(),
        post_routes={
            "/generate-image": FakeResponse(
                json_data={
                    "media": [
                        {
                            "name": "m1",
                            "image": {"generatedImage": {"mediaId": "m1", "fifeUrl": "https://flow/i.png"}},
                        }
                    ]
                }
            )
        },
    )
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=session)
    assets = client.generate_image("a barn at dawn", character_media_ids=["char-1"])

    sent = session.post_calls[0]["json"]
    assert sent["project_id"] == PROJECT_ID
    assert sent["aspect_ratio"] == "IMAGE_ASPECT_RATIO_PORTRAIT"
    assert sent["character_media_ids"] == ["char-1"]
    assert assets[0].media_id == "m1"


def test_generate_image_surfaces_http_error():
    session = FakeSession(
        get_routes=healthy_routes(),
        post_routes={"/generate-image": FakeResponse(status_code=502, text="flow exploded")},
    )
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=session)
    with pytest.raises(FlowkitError, match="HTTP 502"):
        client.generate_image("p")


# --- download guards -------------------------------------------------------


def test_download_rejects_empty_body(tmp_path):
    session = FakeSession(get_routes={"img.png": FakeResponse(content=b"")})
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=session)
    dest = tmp_path / "out.png"
    with pytest.raises(FlowkitError, match="empty file"):
        client.download(ImageAsset("m", "https://flow/img.png"), dest)
    assert not dest.exists()


def test_download_rejects_oversized_image(tmp_path, monkeypatch):
    import automation.flowkit_bridge as bridge

    monkeypatch.setattr(bridge, "MAX_IMAGE_BYTES", 1024)
    session = FakeSession(get_routes={"big.png": FakeResponse(content=b"x" * 4096)})
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=session)
    dest = tmp_path / "big.png"
    with pytest.raises(FlowkitError, match="exceeds"):
        client.download(ImageAsset("m", "https://flow/big.png"), dest)
    # A partial write must not be left behind for the pipeline to trip over.
    assert not dest.exists()


# --- format normalisation --------------------------------------------------


def test_normalise_keeps_accepted_format(tmp_path):
    source = tmp_path / "raw.png"
    source.write_bytes(make_image_bytes())
    final, converted = _normalise_image(source, tmp_path, "01_scene")
    assert converted is False
    assert final.suffix == ".png"
    assert final.exists()


def test_normalise_converts_webp_to_png(tmp_path):
    # webp is NOT in const.FILE_TYPE_IMAGES, so it would skip the zoom-clip
    # branch entirely. This is the regression guard for that.
    assert ".webp" not in ACCEPTED_IMAGE_EXTS
    source = tmp_path / "raw.webp"
    source.write_bytes(make_image_bytes(1024, 1820, fmt="WEBP"))

    final, converted = _normalise_image(source, tmp_path, "01_scene")
    assert converted is True
    assert final.suffix == ".png"
    assert final.exists()
    assert not source.exists()
    with Image.open(final) as img:
        assert img.size == (1024, 1820)


# --- staging ---------------------------------------------------------------


def test_stage_rejects_empty_prompts(tmp_path):
    with pytest.raises(FlowkitError, match="no prompts"):
        stage_flowkit_images([], "task-1", local_videos_dir=tmp_path)


def test_stage_writes_into_task_subdirectory(tmp_path):
    png = make_image_bytes()
    session = FakeSession(
        get_routes=healthy_routes(**{"i.png": FakeResponse(content=png)}),
        post_routes={
            "/generate-image": FakeResponse(
                json_data={
                    "media": [
                        {
                            "name": "m1",
                            "image": {"generatedImage": {"mediaId": "m1", "fifeUrl": "https://flow/i.png"}},
                        }
                    ]
                }
            )
        },
    )
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=session)
    staged = stage_flowkit_images(["a barn at dawn"], "task-abc", source=client, local_videos_dir=tmp_path)

    assert len(staged) == 1
    image = staged[0]
    # Relative, slash-separated, and scoped to the task — this is what
    # preprocess_video resolves against storage/local_videos.
    assert image.path == "task-abc/01_a_barn_at_dawn.png"
    assert (tmp_path / "task-abc" / "01_a_barn_at_dawn.png").exists()
    assert (image.width, image.height) == (1024, 1820)


def test_stage_rejects_low_resolution_and_cleans_up(tmp_path):
    tiny = make_image_bytes(120, 120)
    session = FakeSession(
        get_routes=healthy_routes(**{"i.png": FakeResponse(content=tiny)}),
        post_routes={
            "/generate-image": FakeResponse(
                json_data={
                    "media": [
                        {
                            "name": "m1",
                            "image": {"generatedImage": {"mediaId": "m1", "fifeUrl": "https://flow/i.png"}},
                        }
                    ]
                }
            )
        },
    )
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=session)
    with pytest.raises(FlowkitError, match=f"at least {MIN_MATERIAL_DIMENSION}px"):
        stage_flowkit_images(["tiny"], "task-low", source=client, local_videos_dir=tmp_path)

    assert list((tmp_path / "task-low").glob("*")) == []


def test_stage_numbers_images_in_prompt_order(tmp_path):
    png = make_image_bytes()
    session = FakeSession(
        get_routes=healthy_routes(**{"i.png": FakeResponse(content=png)}),
        post_routes={
            "/generate-image": FakeResponse(
                json_data={
                    "media": [
                        {
                            "name": "m",
                            "image": {"generatedImage": {"mediaId": "m", "fifeUrl": "https://flow/i.png"}},
                        }
                    ]
                }
            )
        },
    )
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=session)
    staged = stage_flowkit_images(
        ["first scene", "second scene", "third scene"],
        "task-n",
        source=client,
        local_videos_dir=tmp_path,
    )
    assert [s.path.split("/")[1] for s in staged] == [
        "01_first_scene.png",
        "02_second_scene.png",
        "03_third_scene.png",
    ]
    assert len(session.post_calls) == 3


def test_stage_does_not_close_a_caller_supplied_source(tmp_path):
    png = make_image_bytes()
    closed = []

    class TrackingSession(FakeSession):
        def close(self):
            closed.append(True)

    session = TrackingSession(
        get_routes=healthy_routes(**{"i.png": FakeResponse(content=png)}),
        post_routes={
            "/generate-image": FakeResponse(
                json_data={
                    "media": [
                        {
                            "name": "m",
                            "image": {"generatedImage": {"mediaId": "m", "fifeUrl": "https://flow/i.png"}},
                        }
                    ]
                }
            )
        },
    )
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=session)
    stage_flowkit_images(["x"], "t", source=client, local_videos_dir=tmp_path)
    assert closed == []


# --- params wiring ---------------------------------------------------------


def test_apply_to_params_switches_to_local_source():
    staged = [
        StagedImage(
            path="t/01_a.png",
            absolute_path="/abs/t/01_a.png",
            prompt="a",
            media_id="m",
            width=1024,
            height=1820,
        )
    ]
    params = apply_to_params({"video_clip_duration": 4}, staged, clip_duration=4)
    assert params["video_source"] == "local"
    assert params["video_materials"] == [{"provider": "flowkit", "url": "t/01_a.png", "duration": 4}]


def test_apply_to_params_rejects_empty():
    with pytest.raises(FlowkitError, match="no staged images"):
        apply_to_params({}, [])


def test_material_shape_matches_materialinfo_model():
    """Guard against schema drift: the pipeline validates materials per task,
    so a mismatch here would only surface after the ledger had claimed topics."""
    from app.models.schema import MaterialInfo

    staged = StagedImage(
        path="t/01_a.png",
        absolute_path="/abs/t/01_a.png",
        prompt="a",
        media_id="m",
        width=1024,
        height=1820,
    )
    material = staged.as_material(clip_duration=5)
    model = MaterialInfo(**material)
    assert model.provider == "flowkit"
    assert model.url == "t/01_a.png"
    assert model.duration == 5


def test_material_provider_is_flowkit_for_provenance():
    staged = StagedImage(
        path="t/01_a.png",
        absolute_path="/abs/t/01_a.png",
        prompt="a",
        media_id="m",
        width=1024,
        height=1820,
    )
    assert staged.as_material()["provider"] == "flowkit"


# --- proxy handling --------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:8100", "http://localhost:8100", "http://127.0.0.2:9000", "http://[::1]:8100"],
)
def test_loopback_url_disables_proxy_use(url):
    """Regression: the sandbox proxy answers /health but 404s deeper paths, which
    looked exactly like a broken flowkit. Loopback must bypass the proxy."""
    client = FlowkitImageSource(base_url=url, session=FakeSession(get_routes=healthy_routes()))
    assert client._session.trust_env is False


def test_remote_url_keeps_proxy_use():
    client = FlowkitImageSource(
        base_url="https://flow.example.com", session=FakeSession(get_routes=healthy_routes())
    )
    assert client._session.trust_env is True


def test_explicit_trust_env_overrides_detection():
    client = FlowkitImageSource(
        base_url="http://127.0.0.1:8100",
        session=FakeSession(get_routes=healthy_routes()),
        trust_env=True,
    )
    assert client._session.trust_env is True


def test_is_loopback_classification():
    from automation.flowkit_bridge import _is_loopback

    assert _is_loopback("http://127.0.0.1:8100") is True
    assert _is_loopback("http://localhost:8100") is True
    assert _is_loopback("https://flow.example.com") is False
    assert _is_loopback("http://192.168.1.10:8100") is False


# --- scrubber integration --------------------------------------------------


class RecordingScrubber:
    """Stand-in for GeminiWatermarkScrubber that records what it was given."""

    def __init__(self):
        self.calls = []

    def scrub(self, path):
        self.calls.append(path)
        return None


def image_session(content):
    return FakeSession(
        get_routes=healthy_routes(**{"i.png": FakeResponse(content=content)}),
        post_routes={
            "/generate-image": FakeResponse(
                json_data={
                    "media": [
                        {
                            "name": "m",
                            "image": {"generatedImage": {"mediaId": "m", "fifeUrl": "https://flow/i.png"}},
                        }
                    ]
                }
            )
        },
    )


def test_stage_scrubs_every_image_before_staging(tmp_path):
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=image_session(make_image_bytes()))
    scrubber = RecordingScrubber()

    staged = stage_flowkit_images(
        ["first scene", "second scene"],
        "task-scrub",
        source=client,
        local_videos_dir=tmp_path,
        scrubber=scrubber,
    )

    assert len(scrubber.calls) == 2
    assert [p.name for p in scrubber.calls] == ["01_first_scene.png", "02_second_scene.png"]
    # Each path handed to the scrubber must be the real staged file.
    assert all(p.exists() for p in scrubber.calls)
    assert [s.path for s in staged] == ["task-scrub/01_first_scene.png", "task-scrub/02_second_scene.png"]


def test_stage_does_not_scrub_a_rejected_low_res_image(tmp_path):
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=image_session(make_image_bytes(120, 120)))
    scrubber = RecordingScrubber()

    with pytest.raises(FlowkitError):
        stage_flowkit_images(
            ["tiny"], "task-low", source=client, local_videos_dir=tmp_path, scrubber=scrubber
        )

    # Resolution is checked first, so a doomed image never costs a scrub.
    assert scrubber.calls == []


def test_stage_without_scrubber_is_a_noop(tmp_path):
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=image_session(make_image_bytes()))
    staged = stage_flowkit_images(["one"], "task-plain", source=client, local_videos_dir=tmp_path)
    assert len(staged) == 1


# --- exact per-still timing ------------------------------------------------


def test_stage_with_holds_renders_exact_clips(tmp_path, monkeypatch):
    """video_clip_duration is one int for the whole task, so a storyboard whose
    holds vary has to be pre-rendered per still or the timing drifts."""
    import automation.flowkit_bridge as bridge

    rendered = []

    def fake_render(image_path, hold_seconds):
        rendered.append((Path(image_path).name, hold_seconds))
        out = Path(f"{image_path}.mp4")
        out.write_bytes(b"fake-mp4")
        return out

    monkeypatch.setattr(bridge, "_render_exact_clip", fake_render)

    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=image_session(make_image_bytes()))
    staged = stage_flowkit_images(
        ["first scene", "second scene"],
        "task-timed",
        source=client,
        local_videos_dir=tmp_path,
        holds=[2.33, 2.67],
    )

    assert rendered == [("01_first_scene.png", 2.33), ("02_second_scene.png", 2.67)]
    assert [s.path for s in staged] == [
        "task-timed/01_first_scene.png.mp4",
        "task-timed/02_second_scene.png.mp4",
    ]
    assert all(s.rendered_clip for s in staged)
    assert [s.duration for s in staged] == [2.33, 2.67]


def test_exact_clips_carry_their_own_duration_into_the_material(tmp_path, monkeypatch):
    import automation.flowkit_bridge as bridge

    def fake_render(image_path, hold_seconds):
        out = Path(f"{image_path}.mp4")
        out.write_bytes(b"fake-mp4")
        return out

    monkeypatch.setattr(bridge, "_render_exact_clip", fake_render)

    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=image_session(make_image_bytes()))
    staged = stage_flowkit_images(
        ["one"], "task-d", source=client, local_videos_dir=tmp_path, holds=[2.67]
    )
    params = apply_to_params({"video_clip_duration": 5}, staged)

    # 2.67 rounds to 3 for the int-typed MaterialInfo.duration; the real length
    # comes from the rendered clip itself.
    assert params["video_materials"][0]["duration"] == 3
    assert params["video_materials"][0]["url"].endswith(".mp4")


def test_holds_length_must_match_prompts(tmp_path):
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=image_session(make_image_bytes()))
    with pytest.raises(FlowkitError, match="holds has 2 entries"):
        stage_flowkit_images(
            ["a", "b", "c"], "task-x", source=client, local_videos_dir=tmp_path, holds=[1.0, 2.0]
        )


def test_without_holds_nothing_is_pre_rendered(tmp_path):
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=image_session(make_image_bytes()))
    staged = stage_flowkit_images(["one"], "task-still", source=client, local_videos_dir=tmp_path)
    assert staged[0].rendered_clip is False
    assert staged[0].duration is None
    assert staged[0].path.endswith(".png")



