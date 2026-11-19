#include "devtrack/diff.hpp"

#include <algorithm>
#include <sstream>

namespace devtrack {

std::vector<std::string> split_lines(const std::string& text) {
    std::vector<std::string> lines;
    std::string cur;
    for (char c : text) {
        if (c == '\n') {
            if (!cur.empty() && cur.back() == '\r') cur.pop_back();  // tolerate CRLF
            lines.push_back(cur);
            cur.clear();
        } else {
            cur += c;
        }
    }
    if (!cur.empty()) lines.push_back(cur);
    return lines;
}

std::vector<DiffLine> diff_lines(const std::vector<std::string>& a,
                                 const std::vector<std::string>& b) {
    const size_t n = a.size(), m = b.size();
    // lcs[i][j] = LCS length of a[i..] and b[j..]
    std::vector<std::vector<int>> lcs(n + 1, std::vector<int>(m + 1, 0));
    for (size_t i = n; i-- > 0;) {
        for (size_t j = m; j-- > 0;) {
            lcs[i][j] = (a[i] == b[j]) ? lcs[i + 1][j + 1] + 1
                                       : std::max(lcs[i + 1][j], lcs[i][j + 1]);
        }
    }
    std::vector<DiffLine> out;
    size_t i = 0, j = 0;
    while (i < n && j < m) {
        if (a[i] == b[j]) {
            out.push_back({Op::Keep, a[i]});
            ++i; ++j;
        } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
            out.push_back({Op::Remove, a[i++]});
        } else {
            out.push_back({Op::Add, b[j++]});
        }
    }
    while (i < n) out.push_back({Op::Remove, a[i++]});
    while (j < m) out.push_back({Op::Add, b[j++]});
    return out;
}

std::string format_diff(const std::vector<DiffLine>& diff) {
    std::ostringstream os;
    for (const auto& d : diff) {
        char prefix = d.op == Op::Keep ? ' ' : (d.op == Op::Remove ? '-' : '+');
        os << prefix << d.text << '\n';
    }
    return os.str();
}

DiffStats diff_stats(const std::vector<DiffLine>& diff) {
    DiffStats s;
    for (const auto& d : diff) {
        if (d.op == Op::Add) ++s.added;
        else if (d.op == Op::Remove) ++s.removed;
    }
    return s;
}

}  // namespace devtrack
