from aws_cdk import assertions


def functions(template):
    return {f["Properties"]["Handler"]: f["Properties"] for f in template.find_resources("AWS::Lambda::Function").values()}


def test_run_worker_has_the_long_timeout_and_one_gb(template):
    fn = functions(template)["jobmecloud.handlers.run_worker.handler"]
    assert fn["Timeout"] == 900 and fn["MemorySize"] == 1024


def test_docs_worker_has_five_minutes_and_one_gb(template):
    fn = functions(template)["jobmecloud.handlers.docs_worker.handler"]
    assert fn["Timeout"] == 300 and fn["MemorySize"] == 1024


def test_workers_are_not_retried_when_they_fail(template):
    configs = template.find_resources("AWS::Lambda::EventInvokeConfig")
    assert len(configs) == 2
    assert all(c["Properties"]["MaximumRetryAttempts"] == 0 for c in configs.values())


def test_api_knows_and_may_invoke_both_workers(template):
    env = functions(template)["jobmecloud.handlers.api.handler"]["Environment"]["Variables"]
    assert "JOBMECLOUD_RUN_FUNCTION" in env and "JOBMECLOUD_DOCS_FUNCTION" in env
    template.has_resource_properties("AWS::IAM::Policy", {"PolicyDocument": {"Statement": assertions.Match.array_with([
        assertions.Match.object_like({"Action": "lambda:InvokeFunction"})])}})


def test_workers_use_the_configured_time_zone(template):
    for handler in ("run_worker", "docs_worker"):
        env = functions(template)[f"jobmecloud.handlers.{handler}.handler"]["Environment"]["Variables"]
        assert env["TZ"] == "UTC"


def test_only_the_api_is_reachable_from_the_internet(template):
    integrations = template.find_resources("AWS::ApiGatewayV2::Integration")
    assert len(integrations) == 1
