#!/usr/bin/env python3
import sys
import argparse
import numpy as np
from PIL import Image
import math
import io

def encode(input_data, width=None, height=None, output_file=None, upscale_width=None, upscale_height=None):
    # Calculate output dimensions
    total_bytes = len(input_data)
    if not width and not height:
        side = math.ceil(math.sqrt(total_bytes / 4))
        width = side
        height = side
    elif width and not height:
        height = math.ceil(total_bytes / (width * 4))
    elif not width and height:
        width = math.ceil(total_bytes / (height * 4))

    total_pixels = width * height
    if total_bytes < total_pixels * 4:
        input_data += b'\x00' * (total_pixels * 4 - total_bytes)
    pixel_data = np.frombuffer(input_data, dtype=np.uint8).reshape((height, width, 4))
    image = Image.fromarray(pixel_data, 'RGBA')

    # Optional upscaling
    if upscale_width or upscale_height:
        up_width = upscale_width if upscale_width else width
        up_height = upscale_height if upscale_height else height
        if (up_width, up_height) != (width, height):
            image = image.resize((up_width, up_height), Image.Resampling.LANCZOS)
    # Output
    if output_file:
        image.save(output_file)
        print(f"Image saved as {output_file}", file=sys.stderr)
    else:
        with io.BytesIO() as img_bytes:
            image.save(img_bytes, format="PNG")
            img_bytes.seek(0)
            sys.stdout.buffer.write(img_bytes.read())

def decode(input_files, width=None, height=None, upscale_width=None, upscale_height=None, output_file=None, orig_length=None):
    input_data = b''
    for fp in input_files:
        if fp == '-':
            img = Image.open(sys.stdin.buffer)
        else:
            img = Image.open(fp)
        img = img.convert("RGBA")
        # Downscale if upscaled (lossy)
        if upscale_width and upscale_height and (img.width, img.height) == (upscale_width, upscale_height):
            img = img.resize((width, height), Image.Resampling.LANCZOS)
        arr = np.array(img)
        flat = arr.flatten()
        input_data += bytes(flat)

    # Trim to original length if provided
    if orig_length is not None:
        input_data = input_data[:orig_length]

    if output_file:
        with open(output_file, "wb") as f:
            f.write(input_data)
        print(f"Decoded binary saved as {output_file}", file=sys.stderr)
    else:
        sys.stdout.buffer.write(input_data)

def main():
    parser = argparse.ArgumentParser(description="Encode/decode arbitrary binary to PNG art (and back again).")
    parser.add_argument("input", nargs="*", type=str, help="Input files (encode: binary, decode: PNG); defaults to stdin if none")
    parser.add_argument("-W", "--width", type=int, help="Width (encode: output, decode: original)")
    parser.add_argument("-H", "--height", type=int, help="Height (encode: output, decode: original)")
    parser.add_argument("-uw", "--upscale-width", type=int, help="Upscaled output width (optional, encode/decode)")
    parser.add_argument("-uh", "--upscale-height", type=int, help="Upscaled output height (optional, encode/decode)")
    parser.add_argument("-f", "--file", type=str, help="Output file path (optional, defaults to stdout)")
    parser.add_argument("-d", "--decode", action="store_true", help="Decode PNG image(s) back to original binary")
    parser.add_argument("-l", "--length", type=int, help="Original binary length (for trimming decoded output)")

    args = parser.parse_args()

    if decode in args:
        # If no input, use stdin as a PNG stream (rare, but possible)
        if not args.input:
            args.input = ['-']
        decode(
            args.input,
            width=args.width,
            height=args.height,
            upscale_width=args.upscale_width,
            upscale_height=args.upscale_height,
            output_file=args.file,
            orig_length=args.length,
        )
    else:
        # Input: read from files or stdin
        if not args.input:
            input_data = sys.stdin.buffer.read()
        else:
            input_data = b""
            for fp in args.input:
                with open(fp, "rb") as f:
                    input_data += f.read()
        encode(
            input_data,
            width=args.width,
            height=args.height,
            output_file=args.file,
            upscale_width=args.upscale_width,
            upscale_height=args.upscale_height,
        )

if __name__ == "__main__":
    main()

