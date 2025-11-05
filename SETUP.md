# Luma Labs Library Setup Guide

## What Was Created

This library includes two nodes for Luma Labs Dream Machine API:

### 1. Luma Image Generation Node
- **Model**: Photon-1 (default) or Photon-Flash-1
- **Features**:
  - Text-to-image generation
  - Image reference (guide generation with existing images)
  - Style reference (apply specific artistic styles)
  - Character reference (create consistent characters)
  - Image modification (edit existing images with prompts)
- **Aspect Ratios**: 1:1, 3:4, 4:3, 9:16, 16:9, 9:21, 21:9
- **Uses**: AsyncLumaAI client with async/await pattern

### 2. Luma Video Generation Node
- **Models**: Ray-2 (default), Ray-Flash-2, Ray-1-6
- **Features**:
  - Text-to-video generation
  - Image-to-video (start and/or end frames)
  - Loop video option
  - Camera motion control (via prompt)
- **Resolutions**: 540p, 720p, 1080p, 4k
- **Durations**: 5s, 10s
- **Uses**: AsyncLumaAI client with async/await pattern

## Installation Steps

1. **Navigate to the library directory**:
   ```bash
   cd /Users/ian/GriptapeNodes/griptape-nodes-library-luma
   ```

2. **Install dependencies using uv**:
   ```bash
   uv pip install -e .
   ```

3. **Get your Luma API key**:
   - Visit https://lumalabs.ai/dream-machine/api/keys
   - Copy your API key

4. **Add the library to Griptape Nodes**:
   - Open Griptape Nodes
   - Go to Settings → Libraries
   - Add the library path: `/Users/ian/GriptapeNodes/griptape-nodes-library-luma`
   - Set the `LUMAAI_API_KEY` secret in the secrets manager

## Usage Examples

### Image Generation
1. Add the "Luma Image Generation" node to your workflow
2. Enter a text prompt
3. (Optional) Add reference images via URLs:
   - Image Reference: Guide the overall generation
   - Style Reference: Apply artistic style
   - Character Reference: Create consistent characters
   - Modify Image: Edit existing images
4. Run the workflow

### Video Generation
1. Add the "Luma Video Generation" node to your workflow
2. Enter a text prompt
3. Select model, resolution, and duration
4. (Optional) Add start/end frame URLs for image-to-video
5. (Optional) Enable loop mode
6. Run the workflow

## API Documentation

- [Image Generation API](https://docs.lumalabs.ai/docs/python-image-generation)
- [Video Generation API](https://docs.lumalabs.ai/docs/python-video-generation)

## Implementation Notes

Both nodes use the async Luma API client as requested:
- `AsyncLumaAI` client with async/await
- Polling pattern for generation completion
- Automatic retry logic with backoff
- Downloads and caches results in Griptape's static files manager
- Full error handling and status reporting

