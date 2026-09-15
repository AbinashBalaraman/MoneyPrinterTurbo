"""Builds the printable storyboard PDF with embedded character photos."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    Image as RLImage,
    KeepTogether,
    HRFlowable,
)
from reportlab.lib.utils import ImageReader
from PIL import Image as PILImage

from src.storyboard.models import StoryboardDocument


def _convert_for_pdf(src_path: str, cache: dict[str, str], tmpdir: str) -> Optional[str]:
    """Converts any Pillow-readable image (incl. webp) to a PDF-safe JPEG.

    Returns the temp JPEG path, or None if the source cannot be read.
    """
    if src_path in cache:
        return cache[src_path]
    try:
        im = PILImage.open(src_path)
        if im.mode in ("RGBA", "LA", "PA"):
            bg = PILImage.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im = bg
        elif im.mode != "RGB":
            im = im.convert("RGB")
        # Downscale huge photos to max 900px wide for PDF size
        im.thumbnail((900, 900), PILImage.LANCZOS)
        safe_name = f"ref_{len(cache)}.jpg"
        out = str(Path(tmpdir) / safe_name)
        im.save(out, "JPEG", quality=88)
        cache[src_path] = out
        return out
    except Exception:
        return None


def _thumb(path: str, cache: dict, tmpdir: str, width: float = 1.5 * inch):
    converted = _convert_for_pdf(path, cache, tmpdir)
    if converted is None:
        return Paragraph("<i>[photo missing]</i>", getSampleStyleSheet()["BodyText"])
    try:
        img = RLImage(converted)
        img._restrictSize(width, 1.5 * inch)
        img.hAlign = "LEFT"
        return img
    except Exception:
        return Paragraph("<i>[photo unreadable]</i>", getSampleStyleSheet()["BodyText"])


class StoryboardPDFBuilder:
    """Renders a StoryboardDocument to PDF."""

    def __init__(self, characters_note: str = "Reference likeness — keep costume/face consistent in every still."):
        self.characters_note = characters_note

    def build(
        self,
        doc: StoryboardDocument,
        output_pdf: str | Path,
        profiles_extra: Optional[dict[str, str]] = None,
    ) -> str:
        out = Path(output_pdf)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmpdir = tempfile.mkdtemp(prefix="storyboard_pdf_")
        cache: dict[str, str] = {}

        styles = getSampleStyleSheet()
        s_title = ParagraphStyle("SBTitle", parent=styles["Title"], fontSize=22, leading=26, alignment=TA_CENTER)
        s_h1 = ParagraphStyle("SBH1", parent=styles["Heading1"], fontSize=15, leading=18, textColor=colors.HexColor("#1a3a2b"), spaceBefore=10, spaceAfter=6)
        s_h2 = ParagraphStyle("SBH2", parent=styles["Heading2"], fontSize=12, leading=15, textColor=colors.HexColor("#2b5d3f"), spaceBefore=8, spaceAfter=4)
        s_body = ParagraphStyle("SBBody", parent=styles["BodyText"], fontSize=9.5, leading=13.5, alignment=TA_LEFT)
        s_small = ParagraphStyle("SBSmall", parent=styles["BodyText"], fontSize=8.5, leading=12, textColor=colors.HexColor("#333333"))
        s_prompt = ParagraphStyle("SBPrompt", parent=styles["Code"] if "Code" in styles else styles["BodyText"], fontName="Courier", fontSize=7.8, leading=11, textColor=colors.HexColor("#1a1a1a"), backColor=colors.HexColor("#f4f1e8"), borderPadding=6)
        s_caption = ParagraphStyle("SBCaption", parent=styles["BodyText"], fontSize=8, leading=10.5, textColor=colors.HexColor("#555555"), alignment=TA_CENTER)
        s_cover_meta = ParagraphStyle("SBCoverMeta", parent=styles["BodyText"], fontSize=10, leading=14, alignment=TA_CENTER)

        story: list = []

        def footer(canvas, pdfdoc):
            canvas.saveState()
            canvas.setFont("Helvetica", 7.5)
            canvas.setFillColor(colors.HexColor("#888888"))
            canvas.drawCentredString(A4[0] / 2, 18, f"Page {pdfdoc.page}  •  {doc.series_id} Ep{doc.episode_num} — {doc.title}  •  Slideshow storyboard")
            canvas.restoreState()

        # ---- Cover ----
        story.append(Spacer(1, 0.5 * inch))
        story.append(Paragraph("SLIDESHOW STORYBOARD", ParagraphStyle("kicker", parent=styles["BodyText"], fontSize=10, leading=12, textColor=colors.HexColor("#7a6a3a"), alignment=TA_CENTER)))
        story.append(Paragraph(doc.title, s_title))
        story.append(Spacer(1, 6))
        story.append(Paragraph(f"{doc.series_id} &nbsp;•&nbsp; Episode {doc.episode_num} &nbsp;•&nbsp; {doc.actual_duration:.0f}s &nbsp;•&nbsp; {doc.total_stills} stills &nbsp;•&nbsp; {doc.style}", s_cover_meta))
        story.append(Spacer(1, 8))
        story.append(HRFlowable(width="80%", thickness=1, color=colors.HexColor("#c9b86a"), spaceAfter=8, spaceBefore=4, hAlign="CENTER"))
        cover_rows = [
            [Paragraph("<b>Cliffhanger</b>", s_small), Paragraph(doc.cliffhanger or "-", s_body)],
            [Paragraph("<b>Next hook</b>", s_small), Paragraph(doc.next_episode_hook or "-", s_body)],
            [Paragraph("<b>How to use</b>", s_small), Paragraph("Generate ONE image per keyframe prompt below (vertical 9:16). Hold each still ~3s with cross-dissolve + slow Ken Burns move. Play narration/voiceover over the holds. Character thumbnails are likeness reference.", s_body)],
        ]
        t = Table(cover_rows, colWidths=[1.3 * inch, 5.5 * inch])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef3ec")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(t)
        story.append(Spacer(1, 10))
        story.append(Paragraph(f"<b>Characters in this episode:</b> {', '.join(sorted(doc.character_photos.keys())) or '(none bound)'}", s_body))
        story.append(Paragraph(f"<i>{self.characters_note}</i>", s_small))

        # ---- Character reference ----
        story.append(Paragraph("Character reference (from Charectors/ folder)", s_h1))
        story.append(Paragraph("Keep these faces/costumes identical in every generated still. First photo per character is the primary likeness.", s_small))
        for name in sorted(doc.character_visuals.keys()):
            # Skip pure location entries from photo grid header? Keep them, they have no photos.
            photos = doc.character_photos.get(name, [])
            story.append(Paragraph(f"{name}", s_h2))
            story.append(Paragraph(doc.character_visuals.get(name, ""), s_body))
            if profiles_extra and name in profiles_extra and profiles_extra[name]:
                story.append(Paragraph(f"<i>Personality: {profiles_extra[name]}</i>", s_small))
            if photos:
                thumbs = [_thumb(p, cache, tmpdir, width=2.0 * inch) for p in photos[:2]]
                # labels row
                cap = [Paragraph(f"{Path(p).name}", s_caption) for p in photos[:2]]
                grid = Table([thumbs, cap], colWidths=[2.2 * inch] * len(thumbs))
                grid.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 4)]))
                story.append(Spacer(1, 4))
                story.append(grid)
            else:
                story.append(Paragraph("<i>No reference photo found in Charectors/ folder.</i>", s_small))
            story.append(Spacer(1, 6))

        # ---- Scenes ----
        for si, scene in enumerate(doc.scenes):
            story.append(PageBreak())
            story.append(Paragraph(f"Scene {scene.scene_index + 1} — {scene.phase} &nbsp;•&nbsp; {scene.time_start:.1f}s–{scene.time_end:.1f}s ({scene.duration:.1f}s) &nbsp;•&nbsp; {len(scene.stills)} stills", s_h1))
            script_rows = [
                [Paragraph("<b>Narration</b>", s_small), Paragraph(scene.narration or "<i>(no narration)</i>", s_body)],
            ]
            if scene.dialogue_text:
                script_rows.append([Paragraph("<b>Dialogue</b>", s_small), Paragraph(f"<b>{scene.dialogue_speaker}</b> ({scene.dialogue_emotion}): “{scene.dialogue_text}”", s_body)])
            script_rows.append([Paragraph("<b>Camera</b>", s_small), Paragraph(scene.camera_directive or "-", s_body)])
            script_rows.append([Paragraph("<b>Action</b>", s_small), Paragraph(scene.action_prompt or "-", s_body)])
            script_rows.append([Paragraph("<b>Cast</b>", s_small), Paragraph(", ".join(scene.bound_characters) or "(environment cutaway)", s_body)])
            st = Table(script_rows, colWidths=[1.3 * inch, 5.5 * inch])
            st.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef3ec")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(st)
            story.append(Spacer(1, 6))

            for still in scene.stills:
                block: list = []
                block.append(Paragraph(f"{still.label} &nbsp;•&nbsp; {still.shot_type} &nbsp;•&nbsp; hold {still.time_start:.1f}s–{still.time_end:.1f}s ({still.hold_seconds:.1f}s)", s_h2))
                block.append(Paragraph(f"<b>Focus:</b> {still.focus}", s_small))
                block.append(Spacer(1, 3))
                # Escape prompt text for Paragraph XML
                esc = still.image_prompt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                block.append(Paragraph(esc, s_prompt))
                block.append(Spacer(1, 3))
                esc_neg = still.negative_prompt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                block.append(Paragraph(f"<b>Negative:</b> {esc_neg}<br/><b>Assemble:</b> hold {still.hold_seconds:.1f}s, {still.transition}, {still.motion_hint}", s_small))
                story.append(KeepTogether(block))
                story.append(Spacer(1, 6))

            # Cast thumbnails for this scene
            if scene.bound_characters:
                story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#bbbbbb"), spaceAfter=4, spaceBefore=4))
                story.append(Paragraph("Likeness reference for this scene:", s_small))
                row: list = []
                caps: list = []
                for cname in scene.bound_characters:
                    plist = doc.character_photos.get(cname, [])
                    if plist:
                        row.append(_thumb(plist[0], cache, tmpdir, width=1.6 * inch))
                        caps.append(Paragraph(f"{cname}", s_caption))
                    else:
                        row.append(Paragraph(f"<i>{cname}: no photo</i>", s_small))
                        caps.append(Paragraph("", s_caption))
                if row:
                    widths = [1.9 * inch] * len(row)
                    gt = Table([row, caps], colWidths=widths)
                    gt.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
                    story.append(gt)

        pdf = SimpleDocTemplate(
            str(out),
            pagesize=A4,
            leftMargin=28,
            rightMargin=28,
            topMargin=32,
            bottomMargin=32,
            title=f"Storyboard — {doc.title} Ep{doc.episode_num}",
            author="shorts_content_engine storyboard",
        )
        pdf.build(story, onFirstPage=footer, onLaterPages=footer)
        return str(out.resolve())
