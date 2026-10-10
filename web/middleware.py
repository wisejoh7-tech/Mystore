from whitenoise.middleware import WhiteNoiseMiddleware, WhiteNoiseFileResponse


async def _async_iter(sync_iterable):
    for item in sync_iterable:
        yield item


class AsyncWhiteNoiseFileResponse(WhiteNoiseFileResponse):
    """
    Subclass WhiteNoiseFileResponse to ensure streaming_content is an asynchronous
    iterator when served under ASGI (e.g., Daphne / Uvicorn), avoiding Django's
    StreamingHttpResponse synchronous iterator warning.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.streaming_content = _async_iter(self.streaming_content)


class AsyncWhiteNoiseMiddleware(WhiteNoiseMiddleware):
    """
    Subclass WhiteNoiseMiddleware to return AsyncWhiteNoiseFileResponse instead
    of standard WhiteNoiseFileResponse.
    """

    @staticmethod
    def serve(static_file, request):
        response = static_file.get_response(request.method, request.META)
        status = int(response.status)
        http_response = AsyncWhiteNoiseFileResponse(response.file or (), status=status)
        # Remove default content-type
        del http_response["content-type"]
        for key, value in response.headers:
            http_response[key] = value
        return http_response
