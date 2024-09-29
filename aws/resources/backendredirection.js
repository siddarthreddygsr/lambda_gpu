function handler(event) {
    var request = event.request;
    var uri = request.uri;

    if (uri === '/api/v1/ws') {
        return {
            statusCode: 301,
            statusDescription: 'Moved Permanently',
            headers: {
                "location": { "value": "ws://<EC2_ENDPOINT>/api/v1/ws" }
            }
        };
    }

    return request;
}