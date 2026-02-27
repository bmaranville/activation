class FetchAPI {
    response_callback = null;
    url = null;

    initialize (response_callback, ready_callback=() => {}, url="/cgi-bin/nact.py") {
        this.response_callback = response_callback;
        this.url = url;
        ready_callback();
    }

    submit(data) {
        const { rest, ...form_data } = data;
        const request_body = new URLSearchParams(form_data);
        // array handling in old URLSearchParams is a bit tricky, so we do it manually:
        rest.forEach((value) => {
            request_body.append('rest[]', value);
        });

        fetch(this.url, {
            method: "POST",
            body: request_body
        })
        .then(response => response.json())
        .then(json => this.response_callback(json))
        .catch(error => this.response_callback({'success':false,'detail':{'fetch error':error}}));
    }
}

const API = new FetchAPI();