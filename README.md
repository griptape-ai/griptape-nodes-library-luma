# Griptape Nodes Library - Luma Labs

This library provides Griptape nodes for interacting with the [Luma Labs Dream Machine API](https://lumalabs.ai/dream-machine/api).

## Features

- **Image Generation**: Generate high-quality images using Luma's Photon models
- **Video Generation**: Create videos using Luma's Ray 2 models
- **Image Reframing**: Change aspect ratios and extend images intelligently
- **Video Reframing**: Change aspect ratios and extend videos intelligently
- **Video Modification**: Apply style transfer and prompt-based editing to videos
- Async implementation for efficient processing
- Support for various aspect ratios and resolutions
- Image and video reference capabilities

## Installation

1. Get your API key from [Luma Labs API Keys](https://lumalabs.ai/dream-machine/api/keys)

2. Add the library to Griptape Nodes and configure your API key in the secrets manager as `LUMAAI_API_KEY`

## Nodes

### Image Generation Node

Generate images from text prompts with support for:

- Text-to-image generation
- Image references with configurable weight
- Style references
- Character references
- Image modification
- Multiple aspect ratios (1:1, 3:4, 4:3, 9:16, 16:9, 9:21, 21:9)
- Two model options: `photon-1` (default) and `photon-flash-1`

### Video Generation Node

Generate videos from text prompts or images with support for:

- Text-to-video generation
- Image-to-video generation with start and end frames
- Ray 2, Ray 2 Flash, and Ray 1.6 models
- Multiple resolutions (540p, 720p, 1080p, 4k) for ray-2 and ray-flash-2
- Duration control (5s or 9s) for ray-2 and ray-flash-2
- Aspect ratios:
  - ray-1-6: 16:9, 9:16, 1:1
  - ray-2 and ray-flash-2: 1:1, 3:4, 4:3, 9:16, 16:9, 9:21, 21:9
- Camera motion controls (pan, tilt, roll, zoom)

### Reframe Nodes (Image & Video)

Change aspect ratios and intelligently extend images or videos to new dimensions:

**Common Features:**

- Convert between aspect ratios (1:1, 4:3, 3:4, 16:9, 9:16, 21:9, 9:21)
- Optional text prompt to guide content generation in new areas
- Advanced parameters for precise control (collapsed by default):
  - **Grid positioning** (`grid_position_x`, `grid_position_y`): Position the original content within the target canvas
  - **Crop bounds** (`x_start`, `x_end`, `y_start`, `y_end`): Define precise boundaries for the original content
  - **Resize dimensions** (`resized_width`, `resized_height`): Specify exact dimensions for the original content before placing

**Image Reframe:**

- Uses Luma's Photon models
- Model selection: `photon-1` or `photon-flash-1`
- Maximum file size: 10 MB

**Video Reframe:**

- Uses Luma's Ray models
- Model selection: `ray-2` (max 10s, higher quality) or `ray-flash-2` (max 30s, faster)
- Maximum file size: 100 MB

#### Understanding Advanced Reframe Parameters

The advanced parameters give you pixel-level control over how your original image/video is positioned within the new aspect ratio:

1. **Target Canvas**: The `aspect_ratio_map` defines the final output dimensions based on your chosen aspect ratio
2. **Original Content**: Your source image/video is first resized to `resized_width` x `resized_height`
3. **Positioning**: The resized content is then placed at (`grid_position_x`, `grid_position_y`) on the canvas
4. **Crop Bounds**: Define the visible area using `x_start`, `x_end`, `y_start`, `y_end` coordinates
5. **Generated Fill**: Luma AI generates content to fill the remaining areas around your original content

This allows precise control over composition while letting AI intelligently extend your content.

### Video Modify Node

Apply style transfer and prompt-based editing to videos using Luma's Ray models:

- Transform video style, appearance, and content while preserving motion
- Model selection: `ray-2` (max 10s) or `ray-flash-2` (max 15s)
- Maximum file size: 100 MB
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

#### What Can You Achieve with Video Modify?

Based on the [Luma documentation](https://docs.lumalabs.ai/docs/modify-video):

- **Preserve Motion**: Full-body motion and facial performance, including choreography, lip sync, and nuanced expressions
- **Restyle Content**: Turn live-action into CG or stylized animation, change wardrobe, props, or overall aesthetic
- **Swap Environments**: Change backgrounds, locations, time periods, or even weather conditions
- **Element-Level Editing**: Isolate and modify specific elements like outfits, faces, or props
- **Add Generative FX**: Layer in smoke, fire, water, and other visual effects

### Utility Nodes

#### List Concepts Node

Fetch all available concepts that can be used in video generation:

- Returns a list of concept strings (e.g., "handheld")
- No inputs required - simply run to retrieve the current list
- Concepts can be used in the Video Generation node to apply specific styles or camera behaviors
- Useful for discovering what concepts are available for your workflow

**How to use concepts:** Pass concept keys in the video generation node. For example, using the "handheld" concept will apply a handheld camera style to your generated video.

#### List Camera Motions Node

Fetch all supported camera motion strings for video generation:

- Returns a list of camera motion phrases (e.g., "camera orbit left", "camera zoom in")
- No inputs required - simply run to retrieve the current list
- Camera motion strings can be included directly in your video generation prompts
- Note: While exact strings are guaranteed to work, syntactically similar phrases also work (though there may be occasional mismatches)

**How to use camera motions:** Include camera motion strings in your prompt text. For example, "A beach sunset, camera pan right" or "Mountain landscape, camera orbit left". The model understands these phrases and will apply the corresponding camera movement to the generated video.

## Documentation

For detailed API documentation, visit:

- [Image Generation API](https://docs.lumalabs.ai/docs/python-image-generation)
- [Video Generation API](https://docs.lumalabs.ai/docs/python-video-generation)
- [Reframe API](https://docs.lumalabs.ai/docs/reframe-video-image)
- [Modify Video API](https://docs.lumalabs.ai/docs/modify-video)

## License

See LICENSE file for details.
