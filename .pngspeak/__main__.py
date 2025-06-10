#!/usr/bin/env python3
import sys, argparse, struct, zlib, os, pathlib, random
import numpy as np

def read_bytes_from_source(n, rand_source):
    if rand_source is not None: # Ensure rand_source can be an empty string
        path = pathlib.Path(rand_source)
        if path.exists():
            with open(rand_source, 'rb') as f:
                return f.read(n)
        # If not a file, treat rand_source as a string to repeat
        encoded_bytes = rand_source.encode('utf-8') # Specify encoding
        if not encoded_bytes: # Handle empty string for --rand
            # Fallback for empty --rand string
            try:
                return os.urandom(n)
            except (NotImplementedError, OSError): # Fallback if os.urandom fails
                return bytes(random.getrandbits(8) for _ in range(n))
        return (encoded_bytes * (n // len(encoded_bytes) + 1))[:n]
    else: # No --rand flag
        try:
            with open('/dev/random', 'rb') as f:
                return f.read(n)
        except OSError: # /dev/random not available or other issue
            try:
                return os.urandom(n) # Preferred fallback
            except (NotImplementedError, OSError): # Fallback if os.urandom also fails
                return bytes(random.getrandbits(8) for _ in range(n)) # Last resort: Python's random

def write_chunk(out, chunk_type, data):
    out.write(struct.pack(">I", len(data)))
    out.write(chunk_type)
    out.write(data)
    checksum = zlib.crc32(chunk_type + data) & 0xffffffff
    out.write(struct.pack(">I", checksum))

def upscale_image(data, width, height, uw, uh):
    bpp = 4
    arr = np.frombuffer(data, dtype=np.uint8).reshape((height, width, bpp))
    new_img = np.zeros((uh, uw, bpp), dtype=np.uint8)

    for y in range(uh):
        for x in range(uw):
            src_x = int(x * width / uw)
            src_y = int(y * height / uh)
            new_img[y, x] = arr[src_y, src_x]

    return new_img.tobytes()

def encode(input_stream, output_stream, cli_width_arg, cli_height_arg, cli_length_arg, rand_source, uw=None, uh=None):
    import tempfile

    # 1. Read all input data first
    # input_stream is expected to be an io.BytesIO or similar seekable stream
    if hasattr(input_stream, 'getvalue'): # Likely an io.BytesIO from our main()
        raw_input_bytes = input_stream.getvalue()
    else: # Fallback for other stream types, read it all
        with tempfile.TemporaryFile() as tf:
            chunk = input_stream.read(8192)
            current_size = 0
            while chunk:
                tf.write(chunk)
                current_size += len(chunk)
                chunk = input_stream.read(8192)
            tf.seek(0)
            raw_input_bytes = tf.read()

    actual_raw_input_len = len(raw_input_bytes)

    # 2. Determine the data_to_embed and the length_for_header based on cli_length_arg
    if cli_length_arg is not None:
        # Always use the user-supplied length for the header
        length_for_header = cli_length_arg
        if actual_raw_input_len < cli_length_arg:
            # Pad raw input data
            padding_needed = cli_length_arg - actual_raw_input_len
            data_to_embed = raw_input_bytes + read_bytes_from_source(padding_needed, rand_source)
        elif actual_raw_input_len > cli_length_arg:
            # Truncate raw input data
            data_to_embed = raw_input_bytes[:cli_length_arg]
        else:
            # Length matches
            data_to_embed = raw_input_bytes
    else:
        # No --length argument, use actual input length for header and data
        length_for_header = actual_raw_input_len
        data_to_embed = raw_input_bytes

    # 3. Calculate PNG grid dimensions (grid_w, grid_h)
    current_data_len = len(data_to_embed)
    bpp = 4
    
    pixels_needed = (current_data_len + bpp - 1) // bpp
    if pixels_needed == 0: # Handles 0-byte data_to_embed (e.g. --length 0 or empty input)
        pixels_needed = 1 # Create a 1x1 pixel image minimum

    grid_w = cli_width_arg
    grid_h = cli_height_arg

    if grid_w is None and grid_h is None:
        grid_w = int(pixels_needed**0.5)
        if grid_w == 0: grid_w = 1
        grid_h = (pixels_needed + grid_w - 1) // grid_w
        if grid_h == 0: grid_h = 1
    elif grid_w is None: # grid_h is provided
        if grid_h <= 0: grid_h = 1
        grid_w = (pixels_needed + grid_h - 1) // grid_h
        if grid_w == 0: grid_w = 1
    elif grid_h is None: # grid_w is provided
        if grid_w <= 0: grid_w = 1
        grid_h = (pixels_needed + grid_w - 1) // grid_w
        if grid_h == 0: grid_h = 1
    else: # Both provided by CLI
        if grid_w <= 0: grid_w = 1
        if grid_h <= 0: grid_h = 1
        
    final_pixel_grid_capacity = grid_w * grid_h * bpp
    
    # 4. Adjust data_to_embed to fit the grid (final_pixel_data)
    final_pixel_data = data_to_embed
    if len(final_pixel_data) < final_pixel_grid_capacity:
        grid_padding_needed = final_pixel_grid_capacity - len(final_pixel_data)
        final_pixel_data += read_bytes_from_source(grid_padding_needed, rand_source)
    elif len(final_pixel_data) > final_pixel_grid_capacity:
        final_pixel_data = final_pixel_data[:final_pixel_grid_capacity] # Truncate to fit grid

    # 5. Write PNG
    output_stream.write(b"\x89PNG\r\n\x1a\n")

    ihdr_w = uw if uw else grid_w
    ihdr_h = uh if uh else grid_h
    ihdr = struct.pack(">IIBBBBB", ihdr_w, ihdr_h, 8, 6, 0, 0, 0)
    write_chunk(output_stream, b'IHDR', ihdr)
    
    # iTXt header with new format using length_for_header (always original input length or --length)
    hex_val_for_header_str = length_for_header.to_bytes((length_for_header.bit_length() + 7) // 8 or 1, 'big').hex()
    len_of_part2_as_str_in_bytes = len(hex_val_for_header_str.encode('utf-8'))
    # Use dynamic length for part1: only as many hex bytes as needed to represent the length
    hex_len_of_part2_str = len_of_part2_as_str_in_bytes.to_bytes((len_of_part2_as_str_in_bytes.bit_length() + 7) // 8 or 1, 'big').hex()
    itxt_text_content = f"{hex_len_of_part2_str} {hex_val_for_header_str}"
    itxt_keyword_and_params = b"license\x00\x00\x00\x00\x00"
    write_chunk(output_stream, b"iTXt", itxt_keyword_and_params + itxt_text_content.encode("utf-8"))

    # IDAT
    data_for_idat_processing = final_pixel_data
    idat_processing_w = grid_w
    idat_processing_h = grid_h

    if uw and uh:
        data_for_idat_processing = upscale_image(final_pixel_data, grid_w, grid_h, uw, uh)
        idat_processing_w = uw
        idat_processing_h = uh

    raw = bytearray()
    for y in range(idat_processing_h):
        raw.append(0)
        start = y * idat_processing_w * bpp
        raw += data_for_idat_processing[start : start + idat_processing_w * bpp]
    compressed = zlib.compress(raw)
    write_chunk(output_stream, b'IDAT', compressed)

    write_chunk(output_stream, b'IEND', b'')

def decode(input_stream, output_stream, length_override, rand_source, width=None, height=None, uw=None, uh=None):
    import png  # you still need `pypng`

    r = png.Reader(file=input_stream)
    w, h, pixels, meta = r.read_flat()
    img_data = bytes(pixels)

    decoded_length_from_header = None

    if 'itxt' in meta:
        for itxt_keyword, lang_tag, translated_keyword, actual_text_content in meta['itxt']:
            if itxt_keyword == 'license':
                try:
                    parts = actual_text_content.strip().split(' ', 1) # Add .strip() before splitting
                    if len(parts) == 2:
                        part1_hex_len_of_part2_str = parts[0]
                        part2_hex_original_file_size_str = parts[1]
                        
                        # ---
                        # Optional: Validate part1 against actual length of part2
                        try:
                            expected_len_of_part2_val_from_header = int.from_bytes(bytes.fromhex(part1_hex_len_of_part2_str), 'big')
                            actual_len_of_part2_str_in_bytes = len(part2_hex_original_file_size_str.encode('utf-8'))
                            if expected_len_of_part2_val_from_header != actual_len_of_part2_str_in_bytes:
                                print(f"Warning: iTXt 'license' header length field mismatch. Expected length of second part string: {expected_len_of_part2_val_from_header}, actual: {actual_len_of_part2_str_in_bytes}.", file=sys.stderr)
                        except ValueError: # Handle potential error from int.from_bytes(bytes.fromhex(...))
                            print(f"Warning: Could not validate part1 of iTXt 'license' header due to hex conversion error.", file=sys.stderr)
                        # ---

                        decoded_length_from_header = int.from_bytes(bytes.fromhex(part2_hex_original_file_size_str), 'big')
                        break # Found and parsed our header
                except ValueError:
                    print("Warning: Could not parse 'license' iTXt header value (ValueError on hex conversion or split).", file=sys.stderr)
                except Exception as e:
                    print(f"Warning: Error processing 'license' iTXt header: {e}", file=sys.stderr)
    else:
        # Fallback: manually parse iTXt chunks if pypng didn't provide them
        input_stream.seek(0)  # Reset stream position
        r_chunks = png.Reader(file=input_stream)
        try:
            for chunk_type, chunk_data in r_chunks.chunks():
                if chunk_type == b'iTXt':
                    # Parse iTXt chunk format: keyword\0lang_tag\0translated_keyword\0\0text
                    null_positions = []
                    for i, byte in enumerate(chunk_data):
                        if byte == 0:
                            null_positions.append(i)
                    
                    if len(null_positions) >= 4:
                        keyword = chunk_data[:null_positions[0]].decode('utf-8')
                        if keyword == 'license':
                            text_start_pos = null_positions[4] + 1
                            actual_text_content = chunk_data[text_start_pos:].decode('utf-8')
                            
                            try:
                                parts = actual_text_content.strip().split(' ', 1)
                                if len(parts) == 2:
                                    part1_hex_len_of_part2_str = parts[0]
                                    part2_hex_original_file_size_str = parts[1]
                                    
                                    # ---
                                    # Optional: Validate part1 against actual length of part2
                                    try:
                                        expected_len_of_part2_val_from_header = int.from_bytes(bytes.fromhex(part1_hex_len_of_part2_str), 'big')
                                        actual_len_of_part2_str_in_bytes = len(part2_hex_original_file_size_str.encode('utf-8'))
                                        if expected_len_of_part2_val_from_header != actual_len_of_part2_str_in_bytes:
                                            print(f"Warning: iTXt 'license' header length field mismatch. Expected length of second part string: {expected_len_of_part2_val_from_header}, actual: {actual_len_of_part2_str_in_bytes}.", file=sys.stderr)
                                    except ValueError: # Handle potential error from int.from_bytes(bytes.fromhex(...))
                                        print(f"Warning: Could not validate part1 of iTXt 'license' header due to hex conversion error.", file=sys.stderr)
                                    # ---

                                    decoded_length_from_header = int.from_bytes(bytes.fromhex(part2_hex_original_file_size_str), 'big')
                                    break # Found and parsed our header
                            except ValueError:
                                print("Warning: Could not parse 'license' iTXt header value (ValueError on hex conversion or split).", file=sys.stderr)
                            except Exception as e:
                                print(f"Warning: Error processing 'license' iTXt header: {e}", file=sys.stderr)
                    break  # Only process the first iTXt chunk
        except Exception as e:
            print(f"Warning: Error reading iTXt chunks: {e}", file=sys.stderr)

    final_length_target = length_override if length_override is not None else decoded_length_from_header

    # Only output up to the embedded data length, not the full RGBA image
    max_embedded_bytes = w * h * 4  # RGBA

    if final_length_target is not None:
        # Output exactly the number of bytes specified by the header (or -l), padding only if needed
        if final_length_target <= max_embedded_bytes:
            output_stream.write(img_data[:final_length_target])
        else:
            output_stream.write(img_data[:max_embedded_bytes])
            padding_needed = final_length_target - max_embedded_bytes
            padding_bytes = read_bytes_from_source(padding_needed, rand_source)
            output_stream.write(padding_bytes)
    else:
        # No length specified from header or CLI, write all embedded data (not padded RGBA)
        output_stream.write(img_data[:max_embedded_bytes])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-e", "--encode", action="count", default=0)
    parser.add_argument("-d", "--decode", action="count", default=0)
    parser.add_argument("-l", "--length", type=int)
    parser.add_argument("-r", "--rand", type=str)
    parser.add_argument("-W", "--width", type=int)
    parser.add_argument("-H", "--height", type=int)
    parser.add_argument("-uw", "--upscale-width", type=int)
    parser.add_argument("-uh", "--upscale-height", type=int)
    parser.add_argument("-f", "--file", type=str)
    args = parser.parse_args()

    op_sequence = []
    for a in sys.argv:
        if a in ("-e", "--encode"): op_sequence.append("encode")
        if a in ("-d", "--decode"): op_sequence.append("decode")

    data_in = sys.stdin.buffer
    data_out = sys.stdout.buffer
    if args.file:
        out = open(args.file, "wb")
    else:
        out = data_out

    for op in op_sequence:
        if op == "encode":
            encode(data_in, out, args.width, args.height, args.length, args.rand, args.upscale_width, args.upscale_height)
            return
        elif op == "decode":
            decode(data_in, out, args.length, args.rand, args.width, args.height, args.upscale_width, args.upscale_height)
            return

if __name__ == "__main__":
    main()