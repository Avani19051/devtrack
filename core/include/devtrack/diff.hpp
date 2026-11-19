// Line-level diff between two revisions, based on longest common subsequence (LCS).
#pragma once
#include <string>
#include <vector>

namespace devtrack {

enum class Op { Keep, Remove, Add };

struct DiffLine {
    Op op;
    std::string text;
};

std::vector<std::string> split_lines(const std::string& text);

// O(n*m) time and memory: fine for config/source files, not meant for huge binaries.
std::vector<DiffLine> diff_lines(const std::vector<std::string>& a,
                                 const std::vector<std::string>& b);

// Renders as " line", "-line", "+line" (one per row).
std::string format_diff(const std::vector<DiffLine>& diff);

struct DiffStats {
    int added = 0;
    int removed = 0;
};
DiffStats diff_stats(const std::vector<DiffLine>& diff);

}  // namespace devtrack
