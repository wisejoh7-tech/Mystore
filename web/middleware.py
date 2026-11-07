from whitenoise.middleware import WhiteNoiseMiddleware, WhiteNoiseFileResponse


async def _async_iter(sync_iterable):
    for item in sync_iterable:
        yield item


class AsyncWhiteNoiseFileResponse(WhiteNoiseFileResponse):
    """
    Subclass WhiteNoiseFileResponse to ensure streaming_content is an asynchronous
    iterator when served under ASGI (e.g., Daphne / Uvicorn), while maintaining
    synchronous iteration support for WSGI (e.g., Gunicorn) and Django test clients.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sync_content = tuple(self.streaming_content)
        self.streaming_content = _async_iter(self._sync_content)

    def __iter__(self):
        return iter(self._sync_content)


class AsyncWhiteNoiseMiddleware(WhiteNoiseMiddleware):
    """
    Subclass WhiteNoiseMiddleware to return AsyncWhiteNoiseFileResponse instead
    of standard WhiteNoiseFileResponse, with fallback to finding files on demand.
    """

    def __call__(self, request):
        if self.autorefresh:
            static_file = self.find_file(request.path_info)
        else:
            static_file = self.files.get(request.path_info)
            if static_file is None and self.use_finders and request.path_info.startswith(self.static_prefix):
                static_file = self.find_file(request.path_info)
                if static_file is not None:
                    self.files[request.path_info] = static_file

        if static_file is not None:
            return self.serve(static_file, request)
        return self.get_response(request)

    @staticmethod
    def serve(static_file, request):
        response = static_file.get_response(request.method, request.META)
        status = int(response.status)
        http_response = AsyncWhiteNoiseFileResponse(response.file or (), status=status)
        if "content-type" in http_response:
            del http_response["content-type"]
        for key, value in response.headers:
            http_response[key] = value
        return http_response
