import json


class FakeOpenAIResponse:
    def __init__(
        self,
        plan=None,
        *,
        output_text=None,
        response_id="resp_test",
        status="completed",
        model=None,
        service_tier="default",
        usage=None,
        output=None,
    ):
        self.id = response_id
        self.status = status
        self.model = model
        self.service_tier = service_tier
        self.usage = usage
        self.output = [] if output is None else output
        self.output_text = json.dumps(plan) if output_text is None else output_text


class FakeResponsesResource:
    def __init__(self, response):
        self.responses = list(response) if isinstance(response, (list, tuple)) else [response]
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        index = len(self.calls) - 1
        if index >= len(self.responses):
            raise AssertionError("Fake OpenAI client received more calls than configured responses")
        response = self.responses[index]
        if isinstance(response, BaseException):
            raise response
        return response


class FakeOpenAIClient:
    def __init__(self, response):
        self.responses = FakeResponsesResource(response)
