#  Copyright (c) 2026 Diego.
#
#  SPDX-License-Identifier: GPL-3.0-or-later
#
#  This file is part of arlo.
#
#  This program is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation, either version 3
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty
#  of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#  See the GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program. If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations
from src.init.identity import get_assistant_name, get_assistant_environment

import asyncio
import os
from pathlib import Path

from pydantic_ai import Agent, BinaryContent
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.ollama import OllamaProvider

from src.init.config import load_dev_file
from src.init.desktop.capture import request_screen_image

VISION_MODEL = get_assistant_environment("VISION_MODEL", load_dev_file()["base_model_name"])
IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

MAX_IMAGE_BYTES = 15 * 1024 * 1024
vision_agent = Agent(
    OllamaModel(
        VISION_MODEL,
        provider=OllamaProvider(
            base_url="http://localhost:11434/v1")),
    instructions=lambda: (
        f"You are {get_assistant_name()}'s image analysis module. "
        "Analyze the supplied image and answer the user's question. "
        "Respond in Spanish unless another language is requested. "
        "Describe only what is supported by the image. "
        "If text is unreadable or something is uncertain, say so. "
        "Do not claim to have interacted with the computer."
    ),
)


async def analyze_image_async(
    image_path: str,
    question: str = "What's in the picture?") -> str:
    """Analyze a local image using the assistant's separate vision model."""
    path = Path(image_path).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError("Path is no file")

    media_type = IMAGE_TYPES.get(path.suffix.lower())

    if media_type is None:
        raise ValueError("Non compatible file, use PNG, JPEG o WebP.")

    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError("Image is larger than 15 MB")

    image = await asyncio.to_thread(path.read_bytes)

    result = await vision_agent.run(
        [question, BinaryContent(data=image,
                media_type=media_type)]
    )

    return result.output

async def analyze_screen(
    question: str = "What's on screen?") -> str:
    """Analyze the primary monitor using the assistant's local vision model."""

    image_data = await asyncio.to_thread(request_screen_image)
    result = await vision_agent.run(
        [question,BinaryContent( data=image_data,
                media_type="image/png")])

    return result.output

def analyze_image(image_path: str,
    question: str = "What's in this image?") -> str:
    """Analyze an image with the local VL model.
    Args:
        image_path: Absolute or relative path to an existing image.
        question: What the assistant should determine from the image.
    Returns:
        A textual description of the image.
    """
    return asyncio.run(analyze_image_async(image_path, question))