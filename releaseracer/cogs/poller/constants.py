import re

#: A regex that processes script tags returned by Discord.
SCRIPT_TAG_REGEX = re.compile(
    r"<script src=\"/assets/([a-f0-9]+)\.js\" [^>]+></script>"
)

#: A regex that extracts the release build from the main JS file.
RELEASE_BUILD_REGEX = re.compile(
    r"{environment:\"[a-z]+\",release:\"(\d+)\",ign"
)

HASH_FIELD = """
main    {hashes.main}
vendor  {hashes.vendor}
"""

