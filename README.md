# Griptape Nodes Library - Luma Labs

This library provides Griptape nodes for interacting with the [Luma Labs Dream Machine API](https://lumalabs.ai/dream-machine/api).

## Features

- **Image Generation**: Generate high-quality images using Luma's Photon models
- **Video Generation**: Create videos using Luma's Ray 2 models
- Async implementation for efficient processing
- Support for various aspect ratios and resolutions
- Image and video reference capabilities

## Installation

1. Install the library using `uv`:

```bash
uv pip install -e .
```

2. Get your API key from [Luma Labs API Keys](https://lumalabs.ai/dream-machine/api/keys)

3. Add the library to Griptape Nodes and configure your API key in the secrets manager as `LUMAAI_API_KEY`

## Nodes

### Image Generation Node

Generate images from text prompts with support for:
- Text-to-image generation
- Image references (up to 4 images)
- Style references
- Character references
- Image modification
- Multiple aspect ratios (1:1, 3:4, 4:3, 9:16, 16:9, 9:21, 21:9)
- Two model options: `photon-1` (default) and `photon-flash-1`

### Video Generation Node

Generate videos from text prompts or images with support for:
- Text-to-video generation
- Image-to-video generation
- Ray 2 and Ray 2 Flash models
- Multiple resolutions (540p, 720p, 1080p, 4k)
- Duration control (5s or 10s)
- Camera motion controls

## Documentation

For detailed API documentation, visit:
- [Image Generation API](https://docs.lumalabs.ai/docs/python-image-generation)
- [Video Generation API](https://docs.lumalabs.ai/docs/python-video-generation)

## License

See LICENSE file for details.

