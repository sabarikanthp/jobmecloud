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


def statements(template):
    out = []
    for policy in template.find_resources("AWS::IAM::Policy").values():
        out += policy["Properties"]["PolicyDocument"]["Statement"]
    return out


def actions(statement):
    value = statement["Action"]
    return [value] if isinstance(value, str) else value


def test_scheduler_has_a_role_that_can_only_invoke_the_run_worker(template):
    roles = [r["Properties"] for r in template.find_resources("AWS::IAM::Role").values()
             if "scheduler.amazonaws.com" in str(r["Properties"]["AssumeRolePolicyDocument"])]
    assert len(roles) == 1
    template.has_resource_properties("AWS::IAM::Policy", {
        "PolicyDocument": {"Statement": assertions.Match.array_with([
            assertions.Match.object_like({"Action": "lambda:InvokeFunction"})])},
        "Roles": assertions.Match.array_with([assertions.Match.object_like({"Ref": assertions.Match.string_like_regexp("SchedulerRole")})]),
    })


def test_api_can_manage_only_our_schedules(template):
    api_env = functions(template)["jobmecloud.handlers.api.handler"]["Environment"]["Variables"]
    assert {"JOBMECLOUD_RUN_FUNCTION_ARN", "JOBMECLOUD_SCHEDULER_ROLE_ARN", "JOBMECLOUD_TIMEZONE"} <= set(api_env)
    manage = [s for s in statements(template) if "scheduler:CreateSchedule" in actions(s)]
    assert len(manage) == 1
    assert sorted(actions(manage[0])) == ["scheduler:CreateSchedule", "scheduler:DeleteSchedule",
                                         "scheduler:GetSchedule", "scheduler:UpdateSchedule"]
    assert "schedule/default/jobmecloud-run-*" in str(manage[0]["Resource"])
    listing = [s for s in statements(template) if actions(s) == ["scheduler:ListSchedules"]]
    assert len(listing) == 1 and listing[0]["Resource"] == "*"
    assert any(actions(s) == ["iam:PassRole"] for s in statements(template))


def ssm_actions_by_function(template):
    out = {}
    for name, policy in template.find_resources("AWS::IAM::Policy").items():
        for s in policy["Properties"]["PolicyDocument"]["Statement"]:
            if any(a.startswith("ssm:") for a in actions(s)):
                out[name] = sorted(actions(s))
    return out


def test_only_the_api_may_write_or_delete_secrets(template):
    by_policy = ssm_actions_by_function(template)
    api = next(a for n, a in by_policy.items() if n.startswith("ApiFunction"))
    assert api == ["ssm:DeleteParameter", "ssm:GetParameter", "ssm:PutParameter"]
    for prefix in ("RunWorkerFunction", "DocsWorkerFunction"):
        worker = next(a for n, a in by_policy.items() if n.startswith(prefix))
        assert worker == ["ssm:GetParameter"], prefix
