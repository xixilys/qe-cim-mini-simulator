#pragma once

#include <cctype>
#include <sstream>
#include <string>
#include <vector>

namespace qebs {
namespace graph_frontdoor {

inline std::string trim_copy(const std::string& value) {
  size_t begin = 0;
  while (begin < value.size() &&
         std::isspace(static_cast<unsigned char>(value[begin])) != 0) {
    ++begin;
  }
  size_t end = value.size();
  while (end > begin &&
         std::isspace(static_cast<unsigned char>(value[end - 1])) != 0) {
    --end;
  }
  return value.substr(begin, end - begin);
}

inline std::vector<std::string> split_cluster_sequence(
    const std::string& sequence) {
  std::vector<std::string> tokens;
  std::stringstream stream(sequence);
  std::string token;
  while (std::getline(stream, token, '>')) {
    token = trim_copy(token);
    if (!token.empty()) {
      tokens.push_back(token);
    }
  }
  return tokens;
}

inline std::string next_token_after(const std::string& sequence,
                                    const std::string& stage_token) {
  const auto tokens = split_cluster_sequence(sequence);
  for (size_t idx = 0; idx < tokens.size(); ++idx) {
    if (tokens[idx] == stage_token) {
      return idx + 1 < tokens.size() ? tokens[idx + 1] : std::string();
    }
  }
  return std::string();
}

inline bool sequence_differs(const std::string& requested,
                             const std::string& resolved) {
  const auto normalized_requested = trim_copy(requested);
  const auto normalized_resolved = trim_copy(resolved);
  return !normalized_requested.empty() &&
         !normalized_resolved.empty() &&
         normalized_requested != normalized_resolved;
}

}  // namespace graph_frontdoor
}  // namespace qebs
