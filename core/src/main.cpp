// dtcore: command-line front end to the C++ core, called by the Python layer.
//
//   dtcore hash <file>              -> prints sha256 hex digest
//   dtcore diff <old> <new>         -> prints line diff; exit 0 if identical, 1 if different
//   dtcore validate <file> <rules>  -> prints one JSON object per issue; exit 0 clean, 1 issues
// Exit code 2 = usage or I/O error.
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>

#include "devtrack/diff.hpp"
#include "devtrack/sha256.hpp"
#include "devtrack/validate.hpp"

using namespace devtrack;

namespace {

std::string read_all(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("cannot open file: " + path);
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

std::string json_escape(const std::string& s) {
    std::string out;
    for (char c : s) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\t': out += "\\t"; break;
            default: out += c;
        }
    }
    return out;
}

int usage() {
    std::cerr << "usage: dtcore hash <file> | diff <old> <new> | validate <file> <rules>\n";
    return 2;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) return usage();
    const std::string cmd = argv[1];
    try {
        if (cmd == "hash" && argc == 3) {
            std::cout << sha256_file(argv[2]) << "\n";
            return 0;
        }
        if (cmd == "diff" && argc == 4) {
            auto d = diff_lines(split_lines(read_all(argv[2])), split_lines(read_all(argv[3])));
            auto st = diff_stats(d);
            std::cout << format_diff(d);
            return (st.added == 0 && st.removed == 0) ? 0 : 1;
        }
        if (cmd == "validate" && argc == 4) {
            auto issues = validate_file(argv[2], load_rules(argv[3]));
            for (const auto& i : issues) {
                std::cout << "{\"rule\":\"" << json_escape(i.rule) << "\",\"message\":\""
                          << json_escape(i.message) << "\",\"line\":" << i.line << "}\n";
            }
            return issues.empty() ? 0 : 1;
        }
    } catch (const std::exception& e) {
        std::cerr << "dtcore: " << e.what() << "\n";
        return 2;
    }
    return usage();
}
