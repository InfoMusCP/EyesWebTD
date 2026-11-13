// Diagnostics of an operator, shown on its Info CHOP (the numeric entries) and Info DAT (all entries, name and text).
// No TouchDesigner dependency.
#pragma once
#include <cstdio>
#include <string>
#include <utility>
#include <vector>

namespace ew_td {

struct InfoEntry {
    std::string name;
    std::string text;
    double value = 0;
    bool numeric = false;
};

class Info {
public:
    void clear() { entries_.clear(); }

    // A numeric entry: a channel of the Info CHOP and a row of the Info DAT. `text` replaces the number in the DAT.
    void number(std::string name, double value, std::string text = "") {
        if (text.empty()) {
            char buffer[32];
            std::snprintf(buffer, sizeof buffer, "%g", value);
            text = buffer;
        }
        entries_.push_back({std::move(name), std::move(text), value, true});
    }
    // A text entry: a row of the Info DAT only.
    void text(std::string name, std::string text) { entries_.push_back({std::move(name), std::move(text), 0, false}); }

    const std::vector<InfoEntry>& entries() const { return entries_; }

    int numericCount() const {
        int n = 0;
        for (const InfoEntry& e : entries_) n += e.numeric ? 1 : 0;
        return n;
    }
    // The i-th numeric entry.
    const InfoEntry& numericAt(int i) const {
        for (const InfoEntry& e : entries_)
            if (e.numeric && i-- == 0) return e;
        return entries_.front();
    }

private:
    std::vector<InfoEntry> entries_;
};

}  // namespace ew_td
