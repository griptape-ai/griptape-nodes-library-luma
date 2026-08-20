# Griptape Nodes Library - Luma Labs

This library provides Griptape nodes for interacting with the [Luma Agents API](https://docs.agents.lumalabs.ai/).

## Features

- **Image Generation**: Generate high-quality images from text prompts with optional style/content reference images
- **Image Editing**: Edit an existing image using AI with a prompt and optional additional references
- **Image Layering**: Decompose an image into semantic RGBA PNG layers
- **Video Generation**: Create videos from text or images using Luma's Ray models
- **Video Reframing**: Change aspect ratios and extend videos intelligently
- **Video Modification**: Apply style transfer and prompt-based editing to videos
- Async implementation for efficient processing
- Support for various aspect ratios and resolutions
- Local image upload handled automatically via Griptape Cloud

## Installation

1. Get your API key from the [Luma API Platform](https://platform.lumalabs.ai)

2. Add the library to Griptape Nodes and configure your API key in the secrets manager as `LUMA_AGENTS_API_KEY`

## Nodes

### Image Generation Node

Generate images from text prompts with support for:

- Text-to-image generation
- Up to 9 reference images to guide style and content via `image_reference` mode
- Multiple aspect ratios (1:1, 3:4, 4:3, 9:16, 16:9, 21:9)
- Two model options: `uni-1` (default) and `uni-1-max` (higher quality)
- Output format: `jpeg` (default, smaller file size) or `png` (lossless)

### Image Edit Node

Edit a source image using Luma AI with support for:

- Required source image (aspect ratio is derived from the source)
- Optional text prompt to describe the desired edit
- Up to 8 additional reference images to guide the edit
- Two model options: `uni-1` (default) and `uni-1-max` (higher quality)
- Output format: `jpeg` (default, smaller file size) or `png` (lossless)

### Image Layer Node

Decompose a source image into semantic RGBA PNG layers with support for:

- Required source image
- Optional text prompt to guide how layers are separated (max 500 characters)
- Resolution control: `1k` or `2k` output layers
- Returns 1–10 RGBA PNG layers, each exposed as an individual output
- Layer metadata (label, description) logged to status output
- Uses the `uni-1` model (the only model supporting the layering API)
- Output is always PNG — RGBA transparency requires lossless format

> **Note:** The layering API requires the `image_layering` capability grant on your Luma account.

### Video Generation Node

Generate videos from text prompts or images with support for:

- Text-to-video generation
- Image-to-video generation with start and end frames
- Multi-keyframe anchoring — up to 64 anchor images with paired position indexes
- HDR output (requires 720p or 1080p resolution)
- The `ray-3.2` model
- Multiple resolutions (360p draft, 540p, 720p, 1080p)
- Duration control (5s or 10s)
- Aspect ratios (1:1, 3:4, 4:3, 9:16, 16:9, 21:9)
- Seamless looping (start/end frame mode)

### Video Reframe Node

Change aspect ratios and intelligently extend videos to new dimensions:

- Convert between aspect ratios (1:1, 4:3, 3:4, 16:9, 9:16, 21:9)
- Optional text prompt to guide content generation in new areas
- The `ray-3.2` model
- Maximum file size: 100 MB
- Advanced source-position controls (collapsed by default) define the normalized rectangle
  the source video occupies inside the output canvas:
  - `x_norm`, `y_norm`: top-left corner of the source rectangle, as fractions of the canvas (may be negative)
  - `w_norm`, `h_norm`: width and height of the source rectangle, as fractions of the canvas (up to 2.0)

  Leave all at 0 to let the model choose the default centered-fit crop.

### Video Modify Node

Apply style transfer and prompt-based editing to videos using Luma's Ray models:

- Transform video style, appearance, and content while preserving motion
- The `ray-3.2` model
- Source video must be 18 seconds or shorter; maximum file size 100 MB
- Optional first frame image to guide the modification
- Required text prompt to direct the modification

#### Modification Modes

The Video Modify node offers 9 modes across three intensity levels, each with three strength variations (1-3):

**Adhere Modes (adhere_1, adhere_2, adhere_3)**

- The output adheres very closely to the source video
- Ideal for subtle enhancements, minor retexturing, or applying light stylistic filters
- Best for: Preserving original content while making minimal changes
- Example use: Color grading, subtle texture changes, gentle aesthetic adjustments

**Flex Modes (flex_1, flex_2, flex_3)**

- The output flexibly adheres to shapes, characters, and details of the source video
- Allows significant stylistic changes while maintaining recognizable elements
- Best for: Balanced transformations that keep the essence of the original
- Example use: Style transfer (live-action to animation), wardrobe changes, prop modifications

**Reimagine Modes (reimagine_1, reimagine_2, reimagine_3)**

- The output adheres much more loosely to the source video
- Best for fundamentally changing the world, style, and transforming content into entirely new forms
- Best for: Dramatic transformations, complete style overhauls
- Example use: Changing time periods, complete environment swaps, transforming characters/objects

## Documentation

For detailed API documentation, visit the [Luma Agents API documentation](https://docs.agents.lumalabs.ai/).

## License

See LICENSE file for details.
