// Joint labels "0", "1", ... shared by the operators that hand a skeleton to the core as a LabelledSet3. The labels are
// built once and grown on demand instead of at every sample of every cook. The core iterates a LabelledSet3 in
// ascending label order (a std::map), so the labels are the same strings the operators always used (std::to_string).
#pragma once
#include <string>
#include <vector>

namespace ew_td {

class JointLabels {
public:
    const std::string& operator[](int joint) {
        while (static_cast<int>(labels_.size()) <= joint) labels_.push_back(std::to_string(labels_.size()));
        return labels_[joint];
    }

private:
    std::vector<std::string> labels_;
};

}  // namespace ew_td
