#include "devtrack/validate.hpp"

#include <fstream>
#include <regex>
#include <sstream>
#include <stdexcept>

#include "devtrack/diff.hpp"

namespace devtrack {
namespace {

std::string trim(const std::string& s) {
    const char* ws = " \t\r\n";
    size_t b = s.find_first_not_of(ws);
    if (b == std::string::npos) return "";
    size_t e = s.find_last_not_of(ws);
    return s.substr(b, e - b + 1);
}

std::vector<std::string> split_csv(const std::string& s) {
    std::vector<std::string> out;
    std::stringstream ss(s);
    std::string item;
    while (std::getline(ss, item, ',')) {
        item = trim(item);
        if (!item.empty()) out.push_back(item);
    }
    return out;
}

std::string base_name(const std::string& path) {
    size_t pos = path.find_last_of("/\\");
    return pos == std::string::npos ? path : path.substr(pos + 1);
}

std::string extension(const std::string& name) {
    size_t pos = name.find_last_of('.');
    return pos == std::string::npos ? "" : name.substr(pos + 1);
}

std::string read_all(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("cannot open file: " + path);
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

}  // namespace

Rules parse_rules(const std::string& text) {
    Rules r;
    int lineno = 0;
    for (const auto& raw : split_lines(text)) {
        ++lineno;
        std::string line = trim(raw);
        if (line.empty() || line[0] == '#') continue;
        size_t eq = line.find('=');
        if (eq == std::string::npos)
            throw std::runtime_error("rules line " + std::to_string(lineno) + ": missing '='");
        std::string key = trim(line.substr(0, eq));
        std::string value = trim(line.substr(eq + 1));
        if (key == "name_pattern") {
            r.name_pattern = value;
        } else if (key == "max_size_kb") {
            r.max_size_kb = std::stol(value);
        } else if (key.rfind("required_keys.", 0) == 0) {
            r.required_keys[key.substr(14)] = split_csv(value);
        } else if (key == "forbid") {
            r.forbidden.push_back(value);
        } else if (key == "no_trailing_whitespace") {
            r.no_trailing_whitespace = (value == "true" || value == "1");
        } else {
            throw std::runtime_error("rules line " + std::to_string(lineno) +
                                     ": unknown rule '" + key + "'");
        }
    }
    return r;
}

Rules load_rules(const std::string& path) { return parse_rules(read_all(path)); }

std::vector<Issue> validate_content(const std::string& filename, const std::string& content,
                                    const Rules& rules) {
    std::vector<Issue> issues;
    const std::string name = base_name(filename);

    if (!rules.name_pattern.empty() && !std::regex_match(name, std::regex(rules.name_pattern))) {
        issues.push_back({"name_pattern", "file name '" + name + "' does not match " +
                                              rules.name_pattern, 0});
    }
    if (rules.max_size_kb >= 0 && long(content.size()) > rules.max_size_kb * 1024) {
        issues.push_back({"max_size_kb", "file is " + std::to_string(content.size() / 1024) +
                                             " KB, limit is " +
                                             std::to_string(rules.max_size_kb) + " KB", 0});
    }
    auto it = rules.required_keys.find(extension(name));
    if (it != rules.required_keys.end()) {
        for (const auto& key : it->second) {
            // Lightweight check: looks for "key" followed by ':' (JSON) or key '=' / ':' (INI/YAML).
            std::regex pat("(\"" + key + "\"\\s*:)|(^\\s*" + key + "\\s*[:=])",
                           std::regex::multiline);
            if (!std::regex_search(content, pat))
                issues.push_back({"required_keys", "missing required key '" + key + "'", 0});
        }
    }
    const auto lines = split_lines(content);
    for (size_t i = 0; i < lines.size(); ++i) {
        for (const auto& bad : rules.forbidden) {
            if (lines[i].find(bad) != std::string::npos)
                issues.push_back({"forbid", "forbidden text '" + bad + "'", int(i + 1)});
        }
        if (rules.no_trailing_whitespace && !lines[i].empty() &&
            (lines[i].back() == ' ' || lines[i].back() == '\t')) {
            issues.push_back({"no_trailing_whitespace", "trailing whitespace", int(i + 1)});
        }
    }
    return issues;
}

std::vector<Issue> validate_file(const std::string& path, const Rules& rules) {
    return validate_content(path, read_all(path), rules);
}

}  // namespace devtrack
