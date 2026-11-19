#include <gtest/gtest.h>

#include "devtrack/diff.hpp"
#include "devtrack/sha256.hpp"
#include "devtrack/validate.hpp"

using namespace devtrack;

// ---------- SHA-256 (NIST test vectors) ----------
TEST(Sha256, EmptyString) {
    EXPECT_EQ(sha256_string(""),
              "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
}

TEST(Sha256, Abc) {
    EXPECT_EQ(sha256_string("abc"),
              "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
}

TEST(Sha256, TwoBlockMessage) {
    EXPECT_EQ(sha256_string("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"),
              "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1");
}

TEST(Sha256, MillionAs) {
    EXPECT_EQ(sha256_string(std::string(1000000, 'a')),
              "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0");
}

TEST(Sha256, IncrementalEqualsOneShot) {
    Sha256 h;
    h.update("hello ");
    h.update("world");
    EXPECT_EQ(h.hexdigest(), sha256_string("hello world"));
}

TEST(Sha256, MissingFileThrows) {
    EXPECT_THROW(sha256_file("/no/such/file"), std::runtime_error);
}

// ---------- Diff ----------
TEST(Diff, IdenticalHasNoChanges) {
    auto d = diff_lines({"a", "b"}, {"a", "b"});
    auto s = diff_stats(d);
    EXPECT_EQ(s.added, 0);
    EXPECT_EQ(s.removed, 0);
}

TEST(Diff, DetectsAddAndRemove) {
    auto d = diff_lines({"a", "b", "c"}, {"a", "c", "d"});
    EXPECT_EQ(format_diff(d), " a\n-b\n c\n+d\n");
    auto s = diff_stats(d);
    EXPECT_EQ(s.added, 1);
    EXPECT_EQ(s.removed, 1);
}

TEST(Diff, EmptySides) {
    EXPECT_EQ(diff_stats(diff_lines({}, {"x", "y"})).added, 2);
    EXPECT_EQ(diff_stats(diff_lines({"x"}, {})).removed, 1);
}

TEST(Diff, SplitLinesHandlesCrlfAndNoTrailingNewline) {
    auto lines = split_lines("one\r\ntwo\nthree");
    ASSERT_EQ(lines.size(), 3u);
    EXPECT_EQ(lines[0], "one");
    EXPECT_EQ(lines[2], "three");
}

// ---------- Validation ----------
TEST(Validate, ParsesRules) {
    Rules r = parse_rules(
        "# comment\nname_pattern=^[a-z_]+\\.json$\nmax_size_kb=1\n"
        "required_keys.json=name, version\nforbid=password=\nno_trailing_whitespace=true\n");
    EXPECT_EQ(r.max_size_kb, 1);
    ASSERT_EQ(r.required_keys["json"].size(), 2u);
    EXPECT_EQ(r.required_keys["json"][1], "version");
    EXPECT_TRUE(r.no_trailing_whitespace);
}

TEST(Validate, UnknownRuleThrows) {
    EXPECT_THROW(parse_rules("colour=blue\n"), std::runtime_error);
}

TEST(Validate, CleanFilePasses) {
    Rules r = parse_rules("name_pattern=^[a-z_]+\\.json$\nrequired_keys.json=name,version\n");
    auto issues = validate_content("ip_block.json", "{\"name\": \"alu\", \"version\": 2}", r);
    EXPECT_TRUE(issues.empty());
}

TEST(Validate, ReportsEachViolation) {
    Rules r = parse_rules(
        "name_pattern=^[a-z_]+\\.json$\nrequired_keys.json=name,version\nforbid=password=\n"
        "no_trailing_whitespace=true\n");
    auto issues = validate_content("Bad-Name.json", "{\"name\": \"x\"} \npassword=123\n", r);
    // name_pattern, missing version, forbidden text (line 2), trailing whitespace (line 1)
    ASSERT_EQ(issues.size(), 4u);
    EXPECT_EQ(issues[0].rule, "name_pattern");
    EXPECT_EQ(issues[1].rule, "required_keys");
    bool saw_forbid_line2 = false;
    for (const auto& i : issues)
        if (i.rule == "forbid" && i.line == 2) saw_forbid_line2 = true;
    EXPECT_TRUE(saw_forbid_line2);
}

TEST(Validate, SizeLimit) {
    Rules r = parse_rules("max_size_kb=1\n");
    EXPECT_EQ(validate_content("a.txt", std::string(2048, 'x'), r).size(), 1u);
    EXPECT_TRUE(validate_content("a.txt", std::string(512, 'x'), r).empty());
}
