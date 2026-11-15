from fastapi import UploadFile

from jobmecloud.importers.text import ImportFileError

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


async def read_upload(file: UploadFile) -> bytes:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImportFileError("That file is too big. The limit is 10 MB.")
    return data
