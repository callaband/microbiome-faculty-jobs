from collector.robots import Robots

THE = """User-agent: *
Disallow: /unijobs/*/jobsrss/*
Disallow: /unijobs/jobsrss/*
Disallow: /unijobs/listings/*/full-time/
"""
EURAXESS = """User-agent: *
Disallow: /core/
Disallow: /*?
Disallow: */api/*
Allow: /jobs
Allow: /jobs/search?page=
"""
NATURE = """User-agent: *
Disallow: /naturecareers/jobsrss/
User-Agent: ClaudeBot
Disallow: /
"""
ACADEMICS = """User-agent: *
Disallow: /preview/

User-agent: Bytespider
Disallow: /
"""
UA = "microbiome-faculty-jobs/1.0 (+https://github.com/x/y)"


def test_wildcard_rules_are_respected():
    r = Robots(THE)
    assert not r.can_fetch(UA, "https://www.timeshighereducation.com/unijobs/jobsrss/?keywords=microbiome")
    assert r.can_fetch(UA, "https://www.timeshighereducation.com/unijobs/listings/?keywords=microbiome")
    assert not r.can_fetch(UA, "https://www.timeshighereducation.com/unijobs/listings/biology/full-time/")


def test_longest_match_and_allow():
    r = Robots(EURAXESS)
    assert r.can_fetch(UA, "https://euraxess.ec.europa.eu/jobs/477785")
    assert r.can_fetch(UA, "https://euraxess.ec.europa.eu/jobs/search")
    assert r.can_fetch(UA, "https://euraxess.ec.europa.eu/jobs/search?page=3")
    # Longest rule wins (RFC 9309): "Allow: /jobs" (5 chars) beats "Disallow: /*?" (3 chars).
    # The EURAXESS reader still avoids query searches, since the file's comments ask for that.
    assert r.can_fetch(UA, "https://euraxess.ec.europa.eu/jobs/search?keywords=microbiome")
    assert not r.can_fetch(UA, "https://euraxess.ec.europa.eu/news?keywords=microbiome")
    assert not r.can_fetch(UA, "https://euraxess.ec.europa.eu/x/api/jobs")


def test_agent_groups():
    r = Robots(NATURE)
    assert not r.can_fetch(UA, "https://www.nature.com/naturecareers/jobsrss/?keywords=x")
    assert r.can_fetch(UA, "https://www.nature.com/naturecareers/job/123/x/")
    assert not r.can_fetch("ClaudeBot/1.0", "https://www.nature.com/anything")
    assert Robots(ACADEMICS).can_fetch(UA, "https://www.academics.com/jobs?search=x")


def test_end_anchor():
    r = Robots("User-agent: *\nDisallow: /*.pdf$\n")
    assert not r.can_fetch(UA, "https://x.org/a/b.pdf")
    assert r.can_fetch(UA, "https://x.org/a/b.pdf?download=1")
