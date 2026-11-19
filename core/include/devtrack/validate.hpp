// Rule-based validation of engineering artifacts before they are versioned.
//
// Rules file format (one rule per line, '#' starts a comment):
//   name_pattern=<ECMAScript regex the file name must match>
//   max_size_kb=<integer>
//   required_keys.<ext>=key1,key2      (top-level keys that must appear, e.g. for .json)
//   forbid=<substring that must not appear, e.g. a hard-coded secret>
//   no_trailing_whitespace=true
#pragma once
#include <map>
#include <string>
#include <vector>

namespace devtrack {

struct Rules {
    std::string name_pattern;
    long max_size_kb = -1;  // -1 = no limit
    std::map<std::string, std::vector<std::string>> required_keys;  // ext -> keys
    std::vector<std::string> forbidden;
    bool no_trailing_whitespace = false;
};

struct Issue {
    std::string rule;     // e.g. "name_pattern"
    std::string message;  // human-readable
    int line = 0;         // 0 = whole file
};

Rules parse_rules(const std::string& text);
Rules load_rules(const std::string& path);

// Validates in-memory content; `filename` is only used for name/extension checks.
std::vector<Issue> validate_content(const std::string& filename, const std::string& content,
                                    const Rules& rules);
std::vector<Issue> validate_file(const std::string& path, const Rules& rules);

}  // namespace devtrack
