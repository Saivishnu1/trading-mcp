def split_message(text: str, max_chars: int = 4000) -> list[str]:
    """Splits a string into lines that fit within Telegram's max message length.

    Tries to split on line endings (keepends=True) to avoid chopping individual logs.
    If a single line is wider than max_chars, it will be sliced at max_chars boundary.
    """
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    current_chunk: list[str] = []
    current_length = 0

    for line in text.splitlines(keepends=True):
        # If a single line itself is longer than max_chars, split it forcibly
        if len(line) > max_chars:
            if current_chunk:
                chunks.append("".join(current_chunk))
                current_chunk = []
                current_length = 0
            for i in range(0, len(line), max_chars):
                chunks.append(line[i:i + max_chars])
            continue

        if current_length + len(line) > max_chars:
            chunks.append("".join(current_chunk))
            current_chunk = [line]
            current_length = len(line)
        else:
            current_chunk.append(line)
            current_length += len(line)

    if current_chunk:
        chunks.append("".join(current_chunk))

    return chunks
