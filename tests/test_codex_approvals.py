from web_admin.operations.codex_approvals import ApprovalRequest, assess_approval_request, parse_approval_request


def test_parse_requires_command() -> None:
    try:
        parse_approval_request({})
    except Exception as exc:
        assert str(exc) == "command is required"
    else:
        raise AssertionError("expected command validation error")


def test_read_only_command_is_likely_allow() -> None:
    assessment = assess_approval_request(ApprovalRequest(command="git diff -- README.md"))
    assert assessment.risk_level == "low"
    assert assessment.recommendation == "likely_allow"
    assert "read_only" in assessment.categories


def test_git_push_requires_inspection() -> None:
    assessment = assess_approval_request(
        ApprovalRequest(command="git push origin main", justification="push completed fix")
    )
    assert assessment.risk_level == "medium"
    assert assessment.recommendation == "inspect_before_allow"
    assert "write" in assessment.categories
    assert "network" in assessment.categories


def test_sudo_rm_rf_is_high_risk() -> None:
    assessment = assess_approval_request(ApprovalRequest(command="sudo rm -rf /tmp/foo"))
    assert assessment.risk_level == "high"
    assert assessment.recommendation == "deny_or_inspect"
    assert "privilege" in assessment.categories
    assert "destructive" in assessment.categories
