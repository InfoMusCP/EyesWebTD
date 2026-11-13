// Declared outputs of an operator, and the channel names that follow from them. Mirrors pyeyesweb.data_models.Output /
// Schema for the outputs that are fixed in size, with the same flat-name rule, so that a CHOP channel has the name of
// the column that PyEyesWeb gives the same output:
//   scalar                  name
//   components (x, y, z)    name_x, name_y, name_z
//   indexed, n entries      name_0 ... name_{n-1}
//   labels x components     name_<label>_<component>
// No TouchDesigner dependency: the schema is also tested on its own.
#pragma once
#include <initializer_list>
#include <string>
#include <utility>
#include <vector>

namespace ew_td {

class Output {
public:
    explicit Output(std::string name) : name_(std::move(name)) {}

    static Output scalar(std::string name) { return Output(std::move(name)); }
    static Output vector(std::string name, std::vector<std::string> components) {
        Output o(std::move(name));
        o.axes_.push_back(std::move(components));
        return o;
    }
    static Output indexed(std::string name, int count) {
        Output o(std::move(name));
        std::vector<std::string> indices;
        for (int i = 0; i < count; ++i) indices.push_back(std::to_string(i));
        o.axes_.push_back(std::move(indices));
        return o;
    }
    static Output grid(std::string name, std::vector<std::string> labels, std::vector<std::string> components) {
        Output o(std::move(name));
        o.axes_.push_back(std::move(labels));
        o.axes_.push_back(std::move(components));
        return o;
    }

    const std::string& name() const { return name_; }

    // Names of the scalar entries, C order.
    std::vector<std::string> flatNames() const {
        std::vector<std::string> out;
        expand(name_, 0, out);
        return out;
    }

private:
    void expand(const std::string& prefix, size_t axis, std::vector<std::string>& out) const {
        if (axis == axes_.size()) { out.push_back(prefix); return; }
        for (const std::string& entry : axes_[axis]) expand(prefix + "_" + entry, axis + 1, out);
    }

    std::string name_;
    std::vector<std::vector<std::string>> axes_;
};

class Schema {
public:
    Schema() = default;
    Schema(std::initializer_list<Output> outputs) : outputs_(outputs) {}

    Schema& add(Output output) {
        outputs_.push_back(std::move(output));
        return *this;
    }

    const std::vector<Output>& outputs() const { return outputs_; }

    // The channel names of the operator, outputs in declaration order.
    std::vector<std::string> flatNames() const {
        std::vector<std::string> out;
        for (const Output& o : outputs_) {
            std::vector<std::string> names = o.flatNames();
            out.insert(out.end(), names.begin(), names.end());
        }
        return out;
    }

    int size() const { return static_cast<int>(flatNames().size()); }

private:
    std::vector<Output> outputs_;
};

}  // namespace ew_td
