import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

import click
import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw
from streamlit_image_coordinates import streamlit_image_coordinates


# ============================================================
# Paths
# ============================================================

BASE_DIR = Path(__file__).parent
IMAGE_DIR = BASE_DIR / "images"
OVERLAY_DIR = BASE_DIR / "overlays"
CSV_PATH = BASE_DIR / "annotations.csv"

OVERLAY_DIR.mkdir(exist_ok=True)
IMAGE_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = ["*.png", "*.jpg", "*.jpeg"]

CATEGORIES = ["standard_plane", "acceptable", "rejected"]

POINT_NAMES = [
    "P1: left PS endpoint",
    "P2: right PS endpoint",
    "P3: fetal head / tangent reference point",
]


# ============================================================
# Helper functions
# ============================================================

def get_image_files():
    image_files = []
    for ext in ALLOWED_EXTENSIONS:
        image_files.extend(list(IMAGE_DIR.glob(ext)))
    return sorted(image_files)


def init_session_state():
    if "image_index" not in st.session_state:
        st.session_state.image_index = 0

    if "current_points" not in st.session_state:
        st.session_state.current_points = []

    if "finished" not in st.session_state:
        st.session_state.finished = False


def load_existing_annotations():
    if CSV_PATH.exists():
        return pd.read_csv(CSV_PATH)

    return pd.DataFrame(columns=[
        "image_name",
        "category",
        "p1_name", "p1_x", "p1_y",
        "p2_name", "p2_x", "p2_y",
        "p3_name", "p3_x", "p3_y",
        "timestamp",
    ])


def save_annotation_to_disk(row):
    df = load_existing_annotations()

    # Overwrite previous annotation for same image
    df = df[df["image_name"] != row["image_name"]]

    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df = df.sort_values("image_name")

    df.to_csv(CSV_PATH, index=False)


def save_overlay_to_disk(image_path, points, category):
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)

    # Draw connecting lines
    if len(points) == 3:
        draw.line([points[0], points[1]], fill="yellow", width=3)
        draw.line([points[1], points[2]], fill="orange", width=3)

    # Draw points
    colors = ["red", "lime", "cyan"]

    for i, ((x, y), color) in enumerate(zip(points, colors), start=1):
        r = 6
        draw.ellipse(
            (x - r, y - r, x + r, y + r),
            fill=color,
            outline="white",
            width=2,
        )
        draw.text((x + 8, y + 8), f"P{i}", fill=color)

    # Draw category
    draw.text((10, 10), f"Category: {category}", fill="white")

    out_path = OVERLAY_DIR / f"{image_path.stem}_overlay.png"
    img.save(out_path)

    return out_path


def delete_overlay_if_rejected(image_path):
    overlay_path = OVERLAY_DIR / f"{image_path.stem}_overlay.png"
    if overlay_path.exists():
        overlay_path.unlink()


def make_annotation_row(image_name, category, points):
    if category == "rejected":
        p1 = p2 = p3 = (None, None)
    else:
        p1, p2, p3 = points

    return {
        "image_name": image_name,
        "category": category,
        "p1_name": "left_PS_endpoint",
        "p1_x": p1[0],
        "p1_y": p1[1],
        "p2_name": "right_PS_endpoint",
        "p2_x": p2[0],
        "p2_y": p2[1],
        "p3_name": "fetal_head_tangent_reference_point",
        "p3_x": p3[0],
        "p3_y": p3[1],
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }


def create_results_zip():
    zip_buffer = BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        if CSV_PATH.exists():
            zip_file.write(CSV_PATH, arcname="annotations.csv")
        else:
            empty_df = load_existing_annotations()
            zip_file.writestr("annotations.csv", empty_df.to_csv(index=False))

        for overlay_path in sorted(OVERLAY_DIR.glob("*.png")):
            zip_file.write(
                overlay_path,
                arcname=f"overlays/{overlay_path.name}",
            )

    zip_buffer.seek(0)
    return zip_buffer


def go_to_image(new_index):
    st.session_state.image_index = new_index
    st.session_state.current_points = []
    st.session_state.finished = False


def get_existing_annotation_for_image(image_name):
    df = load_existing_annotations()

    if df.empty:
        return None

    rows = df[df["image_name"] == image_name]

    if rows.empty:
        return None

    return rows.iloc[0].to_dict()


def load_existing_points_into_session(image_name):
    row = get_existing_annotation_for_image(image_name)

    if row is None:
        return

    if row["category"] == "rejected":
        st.session_state.current_points = []
        return

    try:
        points = [
            (int(row["p1_x"]), int(row["p1_y"])),
            (int(row["p2_x"]), int(row["p2_y"])),
            (int(row["p3_x"]), int(row["p3_y"])),
        ]
        st.session_state.current_points = points
    except Exception:
        st.session_state.current_points = []


# ============================================================
# Fragment: image annotation area
# ============================================================

@st.fragment
def annotation_image_fragment(current_image_path, current_image_name, category):
    current_image = Image.open(current_image_path).convert("RGB")
    orig_w, orig_h = current_image.size

    st.caption(f"Displayed at original size: {orig_w} × {orig_h} px")

    if orig_w != orig_h:
        st.warning(
            f"Image is not square: {orig_w} × {orig_h} px. "
            "It is still displayed without squeezing."
        )

    # Preview image without resizing
    preview = current_image.copy().convert("RGB")
    preview_draw = ImageDraw.Draw(preview)

    points = st.session_state.current_points

    # Draw line P1-P2
    if len(points) >= 2:
        preview_draw.line(
            [points[0], points[1]],
            fill="yellow",
            width=3,
        )

    # Draw line P2-P3
    if len(points) == 3:
        preview_draw.line(
            [points[1], points[2]],
            fill="orange",
            width=3,
        )

    # Draw points
    preview_colors = ["red", "lime", "cyan"]

    for i, (x, y) in enumerate(points):
        r = 6
        preview_draw.ellipse(
            (x - r, y - r, x + r, y + r),
            fill=preview_colors[i],
            outline="white",
            width=2,
        )
        preview_draw.text((x + 8, y + 8), f"P{i + 1}", fill=preview_colors[i])

    if category == "rejected":
        st.info("Rejected image: no points required.")
        st.image(preview, width=orig_w)
        return

    click = streamlit_image_coordinates(
        preview,
        width=orig_w,
        key=f"image_click_{current_image_name}_{len(points)}",
    )

    if click is not None and len(st.session_state.current_points) < 3:
        x = int(click["x"])
        y = int(click["y"])

        if 0 <= x < orig_w and 0 <= y < orig_h:
            st.session_state.current_points.append((x, y))

            # After point 1 and 2: only image updates
            # After point 3: full app rerun so the Save button becomes enabled
            if len(st.session_state.current_points) < 3:
                st.rerun(scope="fragment")
            else:
                st.rerun()
        else:
            st.error(f"Clicked coordinate outside image: x={x}, y={y}")


# ============================================================
# App
# ============================================================

st.set_page_config(
    page_title="AoP Annotation Tool",
    layout="wide",
)

init_session_state()

st.title("AoP Annotation Tool")

image_files = get_image_files()

if len(image_files) == 0:
    st.error("No images found. Please add PNG/JPG images to the images/ folder.")
    st.stop()

n_total = len(image_files)

current_image_path = image_files[st.session_state.image_index]
current_image_name = current_image_path.name

df_existing = load_existing_annotations()
n_done = df_existing["image_name"].nunique() if not df_existing.empty else 0


# ============================================================
# Sidebar
# ============================================================

st.sidebar.header("Progress")

st.sidebar.write(f"Annotated: **{n_done} / {n_total}**")
st.sidebar.progress(n_done / n_total)

st.sidebar.write("---")
st.sidebar.write("Current image:")
st.sidebar.code(current_image_name)

image_names = [p.name for p in image_files]

jump_options = ["-- choose image --"] + image_names

selected_jump = st.sidebar.selectbox(
    "Jump to image",
    jump_options,
    index=0,
    key=f"jump_to_image_selectbox_{st.session_state.image_index}",
)

if selected_jump != "-- choose image --":
    selected_index = image_names.index(selected_jump)
    go_to_image(selected_index)
    st.rerun()

st.sidebar.write("---")

col_prev, col_next = st.sidebar.columns(2)

with col_prev:
    if st.button("Previous", key="previous_button"):
        new_index = max(0, st.session_state.image_index - 1)
        go_to_image(new_index)
        st.rerun()

with col_next:
    if st.button("Next", key="next_button"):
        new_index = min(n_total - 1, st.session_state.image_index + 1)
        go_to_image(new_index)
        st.rerun()

if st.sidebar.button("Reset current points", key="reset_points_button"):
    st.session_state.current_points = []
    st.rerun()

if st.sidebar.button("Load saved annotation for this image", key="load_saved_button"):
    load_existing_points_into_session(current_image_name)
    st.rerun()

st.sidebar.write("---")

if CSV_PATH.exists():
    with open(CSV_PATH, "rb") as f:
        st.sidebar.download_button(
            label="Download annotations.csv",
            data=f,
            file_name="annotations.csv",
            mime="text/csv",
            key="download_csv_button",
        )

zip_buffer = create_results_zip()

st.sidebar.download_button(
    label="Download CSV + overlays ZIP",
    data=zip_buffer,
    file_name="annotation_results.zip",
    mime="application/zip",
    key="download_zip_button",
)


# ============================================================
# Main layout
# ============================================================

left_col, right_col = st.columns([4, 1])

with left_col:
    st.subheader("Image annotation")

    existing_row = get_existing_annotation_for_image(current_image_name)

    if existing_row is not None:
        existing_category = existing_row["category"]

        if existing_category in CATEGORIES:
            default_category_index = CATEGORIES.index(existing_category)
        else:
            default_category_index = None
    else:
        default_category_index = None

    category = st.radio(
        "Select category",
        CATEGORIES,
        index=default_category_index,
        horizontal=True,
        key=f"category_radio_{current_image_name}",
    )

    if category == "rejected" and len(st.session_state.current_points) > 0:
        st.session_state.current_points = []
        st.rerun()

    st.write(
        "**Click 3 points:** "
        "P1 = left PS endpoint, "
        "P2 = right PS endpoint, "
        "P3 = fetal head / tangent reference point."
    )

    annotation_image_fragment(
        current_image_path=current_image_path,
        current_image_name=current_image_name,
        category=category,
    )

    if st.button(
        "Delete last point",
        key=f"delete_last_point_{current_image_name}",
    ):
        if st.session_state.current_points:
            st.session_state.current_points.pop()
            st.rerun()


with right_col:
    st.subheader("Current annotation")

    st.write("Category:")
    if category is None:
        st.write("**Not selected**")
    else:
        st.write(f"**{category}**")

    st.write("Points:")

    # ------------------------------------------------------------
    # Save button logic
    # ------------------------------------------------------------

    category_clean = str(category).strip() if category is not None else None

    if category_clean == "rejected":
        can_save = True
    elif category_clean is None:
        can_save = False
    else:
        can_save = len(st.session_state.current_points) == 3

    if st.session_state.finished:
        st.success("All images have been saved. Please download the results.")

    button_disabled = (not can_save) or st.session_state.finished

    if st.session_state.image_index == n_total - 1:
        save_button_label = "Save final image"
    else:
        save_button_label = "Save and next"

    st.markdown(
        """
        <style>
        div[data-testid="stButton"] > button[kind="primary"] {
            height: 3.2em;
            font-size: 1.15em;
            font-weight: 700;
            border-radius: 10px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    if st.button(
        save_button_label,
        type="primary",
        width='stretch',
        disabled=button_disabled,
        key=f"save_and_next_{current_image_name}",
    ):
        # Re-read category cleanly at click time
        category_clean = str(category).strip() if category is not None else None

        if category_clean is None:
            st.error("Cannot save: please select a category first.")
            st.stop()

        # Validate and prepare points
        if category_clean == "rejected":
            points_for_row = []
        else:
            points_for_row = st.session_state.current_points.copy()

            if len(points_for_row) != 3:
                st.error(
                    f"Cannot save: expected 3 points, but got {len(points_for_row)}. "
                    "Please reset and click 3 points again."
                )
                st.stop()

        # Create CSV row
        row = make_annotation_row(
            image_name=current_image_name,
            category=category_clean,
            points=points_for_row,
        )

        # Save CSV immediately
        save_annotation_to_disk(row)

        # Save or delete overlay immediately
        if category_clean == "rejected":
            delete_overlay_if_rejected(current_image_path)
        else:
            save_overlay_to_disk(
                image_path=current_image_path,
                points=points_for_row,
                category=category_clean,
            )

        # Move to next image or finish
        if st.session_state.image_index < n_total - 1:
            go_to_image(st.session_state.image_index + 1)
            st.rerun()
        else:
            st.session_state.current_points = []
            st.session_state.finished = True
            st.rerun()

    st.write("---")

    if not df_existing.empty:
        st.write("Saved annotations preview:")
        st.dataframe(
            df_existing.tail(10),
            width='stretch',
            height=240,
        )
    else:
        st.info("No annotations saved yet.")
