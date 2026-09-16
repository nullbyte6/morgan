from prompt_toolkit.styles import Style


EDITOR_STYLE = Style.from_dict({
    "status": "reverse",
    "status.modified": "bold",
    "status.filename": "bold",
    "message": "reverse",
})