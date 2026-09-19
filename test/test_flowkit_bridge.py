"""Tests for the flowkit -> AutoShorts image bridge.

No network and no flowkit process: the HTTP session is faked, and images are
real files written with Pillow so the format-normalisation and resolution
checks exercise the same code the live path would.

The last test deliberately validates the material dict against the real
``MaterialInfo`` model. If ``app/models/schema.py`` ever changes shape, that
test fails here rather than at task 1 of an unattended batch.
"""

import io
import time
from pathlib import Path

import pytest
from PIL import Image

from automation.flowkit_bridge import (
    ACCEPTED_IMAGE_EXTS,
    MIN_MATERIAL_DIMENSION,
    FlowkitError,
    FlowkitImageSource,
    ImageAsset,
    ProjectScrubber,
    StagedImage,
    StagedVideo,
    _normalise_image,
    _signed_url_expiry,
    _slugify,
    apply_to_params,
    fetch_project_scenes,
    stage_flowkit_images,
    stage_flowkit_project,
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
    with pytest.raises(FlowkitError, match="no staged media"):
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
    """Stand-in for ProjectScrubber that records what it was given."""

    def __init__(self):
        self.calls = []

    def scrub(self, path):
        self.calls.append(path)
        return None

    def scrub_video(self, path):
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


# --- project mode ----------------------------------------------------------


def project_scene(order, image=True, video=False, narration=True):
    scene = {
        "id": f"scene-{order}",
        "display_order": order,
        "prompt": f"beat {order}",
        "vertical_image_status": "COMPLETED" if image else "PENDING",
        "vertical_image_url": "https://flow/still.png" if image else None,
        "vertical_image_media_id": f"img-{order}",
        "vertical_video_status": "COMPLETED" if video else "PENDING",
        "vertical_video_url": "https://flow/clip.mp4" if video else None,
        "vertical_video_media_id": f"vid-{order}",
        "narrator_text": f"Beat {order}." if narration else None,
    }
    return scene


def project_session(scenes, png=None, mp4=b"fake-mp4-bytes"):
    return FakeSession(
        get_routes=healthy_routes(
            **{
                "/api/projects/proj-1": FakeResponse(
                    json_data={"id": "proj-1", "name": "Test Project"}
                ),
                "/api/videos?project_id=proj-1": FakeResponse(
                    json_data=[{"id": "vid-1"}]
                ),
                "/api/scenes?video_id=vid-1": FakeResponse(json_data=scenes),
                "still.png": FakeResponse(content=png if png is not None else make_image_bytes()),
                "clip.mp4": FakeResponse(content=mp4),
            }
        )
    )


def test_fetch_project_scenes_sorts_by_display_order():
    scenes = [project_scene(2), project_scene(0), project_scene(1)]
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=project_session(scenes))
    project, ordered = fetch_project_scenes(client, "proj-1")
    assert project["name"] == "Test Project"
    assert [s["display_order"] for s in ordered] == [0, 1, 2]


def test_fetch_project_unknown_ref_fails():
    session = FakeSession(
        get_routes=healthy_routes(
            **{"/api/projects/nope": FakeResponse(status_code=404, text="gone"),
             "/api/projects": FakeResponse(json_data=[])} 
        )
    )
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=session)
    with pytest.raises(FlowkitError, match="not found"):
        fetch_project_scenes(client, "nope")


def test_project_mode_prefers_video_over_still(tmp_path):
    scenes = [project_scene(0, image=True, video=True)]
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=project_session(scenes))
    staged, narration = stage_flowkit_project(
        "proj-1", "task-pv", source=client, local_videos_dir=tmp_path
    )
    assert len(staged) == 1
    assert isinstance(staged[0], StagedVideo)
    assert staged[0].path == "task-pv/00_scene.mp4"
    assert (tmp_path / "task-pv" / "00_scene.mp4").exists()
    assert narration == "Beat 0."
    material = staged[0].as_material()
    assert material["provider"] == "flowkit"
    assert material["url"] == "task-pv/00_scene.mp4"


def test_project_mode_falls_back_to_still(tmp_path):
    scenes = [project_scene(0, image=True, video=False)]
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=project_session(scenes))
    staged, _ = stage_flowkit_project(
        "proj-1", "task-ps", source=client, local_videos_dir=tmp_path
    )
    assert len(staged) == 1
    assert isinstance(staged[0], StagedImage)
    assert staged[0].path.endswith(".png")


def test_project_mode_stills_only_skips_videos(tmp_path):
    scenes = [project_scene(0, image=True, video=True)]
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=project_session(scenes))
    staged, _ = stage_flowkit_project(
        "proj-1", "task-so", source=client, local_videos_dir=tmp_path, media="still"
    )
    assert len(staged) == 1
    assert isinstance(staged[0], StagedImage)


def test_project_mode_video_only_skips_stills(tmp_path):
    scenes = [project_scene(0, image=True, video=False)]
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=project_session(scenes))
    with pytest.raises(FlowkitError, match="no completed videos"):
        stage_flowkit_project(
            "proj-1", "task-vo", source=client, local_videos_dir=tmp_path, media="video"
        )


def test_project_mode_rejects_bad_media_mode(tmp_path):
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=project_session([]))
    with pytest.raises(FlowkitError, match="unknown media mode"):
        stage_flowkit_project("proj-1", "task-x", source=client, local_videos_dir=tmp_path, media="film")


def test_project_mode_without_completed_media_fails(tmp_path):
    scenes = [project_scene(0, image=False, video=False)]
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=project_session(scenes))
    with pytest.raises(FlowkitError, match="no completed media"):
        stage_flowkit_project("proj-1", "task-e", source=client, local_videos_dir=tmp_path)


def test_absolute_urls_keep_manifest_portable_outside_local_videos(tmp_path):
    from automation.flowkit_bridge import _absolute_material_urls

    staged = [
        StagedVideo(
            path="t/00_scene.mp4", absolute_path=str(tmp_path / "t" / "00_scene.mp4"),
            prompt="p", media_id="m",
        )
    ]
    params = apply_to_params({"video_clip_duration": 5}, staged)
    assert params["video_materials"][0]["url"] == "t/00_scene.mp4"
    _absolute_material_urls(params, staged)
    assert params["video_materials"][0]["url"] == str(tmp_path / "t" / "00_scene.mp4")


def test_project_materials_validate_as_materialinfo():
    from app.models.schema import MaterialInfo

    video = StagedVideo(
        path="t/00_scene.mp4", absolute_path="/abs/t/00_scene.mp4",
        prompt="p", media_id="m", scene_id="s",
    )
    model = MaterialInfo(**video.as_material())
    assert model.provider == "flowkit"
    assert model.url == "t/00_scene.mp4"


# --- project scrubber (in-project engine) ----------------------------------


def test_project_scrubber_loads_sce_engine():
    scrubber = ProjectScrubber()
    assert scrubber.STILL_PROFILE == "gemini_bottom_right"
    assert scrubber.VIDEO_PROFILE == "veo_bottom_right"


def test_project_scrubber_reports_ffmpeg_availability(monkeypatch):
    import shutil

    scrubber = ProjectScrubber()
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert scrubber.available() is False
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/ffmpeg")
    assert scrubber.available() is True


class FakeEngine:
    """Stand-in for the SCE WatermarkScrubber."""

    def __init__(self, ok=True, calls=None):
        self.ok = ok
        self.calls = calls if calls is not None else []

    def scrub_video(self, src, dest, profile=""):
        self.calls.append({"src": src, "dest": dest, "profile": profile})
        if self.ok:
            Path(dest).write_bytes(b"scrubbed")
        return self.ok


def test_project_scrubber_replaces_still_in_place(tmp_path, monkeypatch):
    scrubber = ProjectScrubber.__new__(ProjectScrubber)
    engine = FakeEngine()
    object.__setattr__(scrubber, "_impl", engine)
    target = tmp_path / "still.png"
    target.write_bytes(b"original")
    scrubber.scrub(target)
    assert target.read_bytes() == b"scrubbed"
    assert engine.calls[0]["profile"] == "gemini_bottom_right"


def test_project_scrubber_uses_veo_profile_for_video(tmp_path):
    scrubber = ProjectScrubber.__new__(ProjectScrubber)
    engine = FakeEngine()
    object.__setattr__(scrubber, "_impl", engine)
    target = tmp_path / "clip.mp4"
    target.write_bytes(b"original")
    scrubber.scrub_video(target)
    assert target.read_bytes() == b"scrubbed"
    assert engine.calls[0]["profile"] == "veo_bottom_right"


def test_project_scrubber_failure_is_loud_and_keeps_original(tmp_path):
    scrubber = ProjectScrubber.__new__(ProjectScrubber)
    object.__setattr__(scrubber, "_impl", FakeEngine(ok=False))
    target = tmp_path / "still.png"
    target.write_bytes(b"original")
    with pytest.raises(FlowkitError, match="scrub failed"):
        scrubber.scrub(target)
    assert target.read_bytes() == b"original"


# ---------------------------------------------------------------------------
# Signed-URL expiry
#
# Flow serves media through signed URLs that stop working a few days after
# generation, while the database goes on reporting the scene as COMPLETED.
# Measured on the live project: 13 of 13 URLs expired, ~5 days past, and a plain
# curl of the same URL also returned 403. Staging used to walk the scenes and die
# partway through; it now refuses up front when nothing is usable.
# ---------------------------------------------------------------------------


def _signed(path: str, expires: int) -> str:
    return f"https://flow/{path}?Expires={expires}&Signature=abc"


def _scene_with_urls(order, image_url=None, video_url=None):
    scene = project_scene(order, image=bool(image_url), video=bool(video_url))
    scene["vertical_image_url"] = image_url
    scene["vertical_video_url"] = video_url
    return scene


def test_signed_url_expiry_reads_the_expires_param():
    assert _signed_url_expiry(_signed("x.png", 1234)) == 1234


def test_signed_url_expiry_is_case_insensitive():
    assert _signed_url_expiry("https://flow/x.png?expires=99") == 99


def test_signed_url_expiry_is_none_when_absent_or_unparseable():
    """None means "just try it" -- never "expired"."""
    assert _signed_url_expiry("https://flow/x.png") is None
    assert _signed_url_expiry("https://flow/x.png?Expires=notanumber") is None
    assert _signed_url_expiry("not a url at all") is None


def test_all_expired_media_is_refused_before_any_download(tmp_path):
    past = int(time.time()) - 5 * 86400
    scenes = [
        _scene_with_urls(0, image_url=_signed("still.png", past)),
        _scene_with_urls(1, image_url=_signed("still.png", past)),
    ]
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=project_session(scenes))
    with pytest.raises(FlowkitError, match="expired"):
        stage_flowkit_project(
            "proj-1", "task-expired", source=client, local_videos_dir=tmp_path
        )


def test_still_valid_media_is_staged_normally(tmp_path):
    future = int(time.time()) + 86400
    scenes = [
        _scene_with_urls(0, image_url=_signed("still.png", future)),
        _scene_with_urls(1, image_url=_signed("still.png", future)),
    ]
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=project_session(scenes))
    staged, _ = stage_flowkit_project(
        "proj-1", "task-live", source=client, local_videos_dir=tmp_path
    )
    assert len(staged) == 2


def test_url_without_expiry_is_attempted_rather_than_refused(tmp_path):
    """An unsigned or unfamiliar URL must be tried, not treated as expired."""
    scenes = [_scene_with_urls(0, image_url="https://flow/still.png")]
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=project_session(scenes))
    staged, _ = stage_flowkit_project(
        "proj-1", "task-unsigned", source=client, local_videos_dir=tmp_path
    )
    assert len(staged) == 1


def test_media_mode_only_considers_the_urls_it_will_use(tmp_path):
    """media='video' must not refuse because the *stills* expired."""
    past = int(time.time()) - 86400
    future = int(time.time()) + 86400
    scenes = [
        _scene_with_urls(
            0,
            image_url=_signed("still.png", past),
            video_url=_signed("clip.mp4", future),
        )
    ]
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=project_session(scenes))
    staged, _ = stage_flowkit_project(
        "proj-1", "task-video", source=client, local_videos_dir=tmp_path, media="video"
    )
    assert len(staged) == 1
    assert isinstance(staged[0], StagedVideo)


def test_expired_videos_do_not_block_the_stills_fallback(tmp_path):
    """media='auto' with expired videos but live stills still stages."""
    past = int(time.time()) - 86400
    future = int(time.time()) + 86400
    scenes = [
        _scene_with_urls(
            0,
            image_url=_signed("still.png", future),
            video_url=_signed("clip.mp4", past),
        )
    ]
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=project_session(scenes))
    staged, _ = stage_flowkit_project(
        "proj-1", "task-fallback", source=client, local_videos_dir=tmp_path
    )
    assert len(staged) == 1
    assert isinstance(staged[0], StagedImage)


def test_no_scenes_does_not_trip_the_expiry_check(tmp_path):
    """An empty project must fail for its own reason, not as "expired"."""
    client = FlowkitImageSource(base_url=FLOWKIT_URL, session=project_session([]))
    with pytest.raises(FlowkitError, match="no completed"):
        stage_flowkit_project(
            "proj-1", "task-empty", source=client, local_videos_dir=tmp_path
        )



