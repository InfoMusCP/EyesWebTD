// What the four GenericModel* operators share (not an operator: the CMake file globs only *.cpp).
//
// THE MODEL. A generic model (masses, springs, rest values) is data of the user, a ew::humanoid::MassSpringModel that
// PyEyesWeb builds by hand or loads from an EyesWeb XML file. A CHOP cannot take it as channels (it has names,
// topology and a dozen values per spring), so the operators take it as the EyesWeb XML itself, in one of two ways:
//   Modelxml   string parameter: the XML text. Bind it to a Text DAT with an expression, op('model').text, and the model
//              is edited in the network, with no file. Used when it is not empty.
//   Modelfile  string parameter: path of an EyesWeb XML model file, used when Modelxml is empty.
// The model is reloaded when the text or the file (path or modification time) changes; a change of model is structural
// and restarts the state, as setting `feature.model` does in PyEyesWeb. A model that cannot be read is INVALID_INPUT
// with the reason of the core (the channels are then one placeholder channel with the output name, all zero).
//
// THE CHANNELS. PyEyesWeb names the points of a frame; a CHOP has channels. The core keeps masses and springs sorted by
// name (std::map), which is also the order of `mass_names`, `spring_names` and `output_labels` in PyEyesWeb: the operators
// take and give the points in that order (ascending by name, byte order), x y z of each (joint-major), and name the
// channels as PyEyesWeb does (<output>_<name>_<x|y|z>). Input frames therefore need no `labels` / `joint_map`: reorder
// your joints (Select CHOP, Merge) into the sorted order, which the output channel names of the operator show. The Info
// DAT lists the names that the input has to follow (`input_names`).
//
// THE FRAME. Every sample of the input is one frame. As in PyEyesWeb, a point with a NaN component is missing (a dropout
// the model handles), an infinite value or a frame whose every value is NaN is INVALID_INPUT for that sample (its
// output is zero and the model is not fed), a wrong channel count is INVALID_INPUT for the cook.
#pragma once
#include <algorithm>
#include <cmath>
#include <filesystem>
#include <limits>
#include <memory>
#include <optional>
#include <string>
#include <system_error>
#include <vector>
#include "CPlusPlus_Common.h"
#include "ew/common/labelled_set.h"
#include "ew/features/humanoid/generic_model_runner.h"
#include "ew/features/humanoid/mass_spring_model.h"
#include "ew_td/input.h"
#include "ew_td/params.h"
#include "ew_td/schema.h"
#include "ew_td/status.h"

namespace gm {

using ew::humanoid::MassSpringModel;

// The model of the operator, read from the parameters Modelxml / Modelfile and kept until they change.
class ModelSource {
public:
    // The model; ew_td::InputError when none is set or it cannot be read.
    const MassSpringModel& get(const TD::OP_Inputs* in) const {
        refresh(in);
        if (!error_.empty()) throw ew_td::InputError(error_);
        return *model_;
    }
    // The model, or nullptr (no model, unreadable): for the schema, which must not throw.
    const MassSpringModel* peek(const TD::OP_Inputs* in) const {
        refresh(in);
        return error_.empty() ? model_.get() : nullptr;
    }
    // Incremented at every new model (also when it fails to load).
    int generation() const { return generation_; }

private:
    void refresh(const TD::OP_Inputs* in) const {
        const std::string xml = in->getParString("Modelxml");
        const std::string path = in->getParString("Modelfile");
        std::string key;
        if (!xml.empty()) {
            key = "x" + xml;
        } else if (!path.empty()) {
            std::error_code ec;
            const auto stamp = std::filesystem::last_write_time(std::filesystem::u8path(path), ec);
            key = "f" + path + "|" + (ec ? std::string("?") : std::to_string(stamp.time_since_epoch().count()));
        }
        if (generation_ > 0 && key == key_) return;
        key_ = key;
        ++generation_;
        model_.reset();
        error_.clear();
        try {
            if (!xml.empty()) model_ = std::make_unique<MassSpringModel>(MassSpringModel::fromXmlString(xml));
            else if (!path.empty()) model_ = std::make_unique<MassSpringModel>(MassSpringModel::fromXmlFile(path));
            else error_ = "no model: set Modelxml (the EyesWeb XML text) or Modelfile (the path of an XML file)";
        } catch (const std::exception& e) {
            error_ = std::string("model: ") + e.what();
        }
    }

    mutable std::unique_ptr<MassSpringModel> model_;
    mutable std::string key_, error_;
    mutable int generation_ = 0;
};

inline std::vector<std::string> massNames(const MassSpringModel& m) { return ew::humanoid::massLabels(m); }
inline std::vector<std::string> springNames(const MassSpringModel& m) {
    std::vector<std::string> names;
    for (const auto& entry : m.springs()) names.push_back(entry.first);
    return names;
}

inline void declareModel(ew_td::Params& p) {
    p.page("Model");
    p.string("Modelxml", "Model XML", "");
    p.string("Modelfile", "Model File", "");
}

inline ew::Point3 point3(const TD::OP_Inputs* in, const char* name) {
    const auto v = ew_td::vector3(in, name);
    return {v[0], v[1], v[2]};
}

// The parameters of the base block (GenericModelParams), the same names and defaults as PyEyesWeb.
inline void declareBase(ew_td::Params& p, bool floorAndLengths = true) {
    using ew_td::Range;
    p.page("Model Dynamics");
    p.vector3("Refdir", "Reference Direction", {1.0, 0.0, 0.0}, Range::slider(-1, 1));
    p.number("Integrationstep", "Integration Step (s)", 0.001, Range::atLeast(1e-9, 0.01));
    p.vector3("Gravity", "Gravity", {0.0, 0.0, 0.0}, Range::slider(-10, 10));
    p.number("Damping", "Damping", 10.0, Range::slider(0, 20));
    p.number("Viscosity", "Viscosity", 0.0, Range::slider(0, 10));
    p.toggle("Lengthforces", "Length Forces", true);
    p.toggle("Rotationforces", "Rotation Forces", true);
    p.toggle("Groundinteraction", "Ground Interaction", false);
    p.vector3("Floor", "Floor Position", {0.0, 0.0, 0.0}, Range::slider(-10, 10));
    if (floorAndLengths) p.toggle("Useinputlengths", "Use Input Lengths", false);
}

template <class Params>
void readBase(const TD::OP_Inputs* in, Params& p) {
    p.referenceDirection = point3(in, "Refdir");
    p.integrationStep = in->getParDouble("Integrationstep");
    p.gravity = point3(in, "Gravity");
    p.damping = in->getParDouble("Damping");
    p.viscosity = in->getParDouble("Viscosity");
    p.lengthForces = in->getParInt("Lengthforces") != 0;
    p.rotationForces = in->getParInt("Rotationforces") != 0;
    p.groundInteraction = in->getParInt("Groundinteraction") != 0;
    p.floorPosition = point3(in, "Floor");
    p.useInputLengths = in->getParInt("Useinputlengths") != 0;
}

// Output channels of a labelled set of points: `name_<label>_x|y|z`, or a placeholder when there is no model.
inline ew_td::Output pointsOutput(const std::string& name, const MassSpringModel* model, bool springs) {
    if (!model) return ew_td::Output::scalar(name);
    return ew_td::Output::grid(name, springs ? springNames(*model) : massNames(*model), {"x", "y", "z"});
}

// Why sample `s` of the input is not a frame (empty string when it is one): an infinite value, or nothing but NaN.
inline std::string frameProblem(const ew_td::InputView& input, int s) {
    bool anyFinite = false;
    for (int c = 0; c < input.channels(); ++c) {
        const double v = input.at(c, s);
        if (std::isinf(v)) return "infinite values";
        if (!std::isnan(v)) anyFinite = true;
    }
    return anyFinite ? "" : "no joint present in the frame";
}

// The points of sample `s` as the core takes them, keyed by `names` (rows with a NaN are missing).
inline ew::LabelledSet3 readNamedPoints(const ew_td::InputView& input, int s, const std::vector<std::string>& names) {
    ew::LabelledSet3 set;
    for (size_t i = 0; i < names.size(); ++i) {
        const double x = input.at(static_cast<int>(3 * i), s), y = input.at(static_cast<int>(3 * i + 1), s),
                     z = input.at(static_cast<int>(3 * i + 2), s);
        if (std::isnan(x) || std::isnan(y) || std::isnan(z)) continue;
        set.emplace(names[i], ew::Point3{x, y, z});
    }
    return set;
}

// Writes the points of `set` at sample `s` from channel `first`, in the order of `labels` (NaN when missing).
inline void writePoints(TD::CHOP_Output* out, int first, int s, const ew::LabelledSet3& set,
                        const std::vector<std::string>& labels) {
    const float nan = std::numeric_limits<float>::quiet_NaN();
    for (size_t i = 0; i < labels.size(); ++i) {
        const ew::Point3* p = ew::findPoint(set, labels[i]);
        const int c = first + static_cast<int>(3 * i);
        out->channels[c][s] = p ? static_cast<float>(p->x) : nan;
        out->channels[c + 1][s] = p ? static_cast<float>(p->y) : nan;
        out->channels[c + 2][s] = p ? static_cast<float>(p->z) : nan;
    }
}

inline void requireChannels(const ew_td::InputView& input, size_t points, const char* what, const std::vector<std::string>& names) {
    if (input.channels() == static_cast<int>(3 * points)) return;
    std::string list;
    for (const std::string& n : names) list += (list.empty() ? "" : ", ") + n;
    throw ew_td::InputError("Input has " + std::to_string(input.channels()) + " channels, the model has " +
                            std::to_string(points) + " " + what + " (x y z each, in the order " + list + ")");
}

inline std::string joined(const std::vector<std::string>& names) {
    std::string s;
    for (const std::string& n : names) s += (s.empty() ? "" : " ") + n;
    return s;
}

// Holder of the core feature: built at the first use with (model, params); at the next cooks the new parameters (and the
// model, whose topology the core compares) go through adoptParams, which keeps the state for live parameters.
template <class Feature>
class ModelSlot {
public:
    Feature& get(const MassSpringModel& model, const typename Feature::Params& params) {
        if (!feature_) {
            feature_ = std::make_unique<Feature>(model, params);
        } else {
            const Feature fresh(model, params);
            feature_->adoptParams(fresh);
        }
        return *feature_;
    }
    void drop() { feature_.reset(); }
    Feature* peek() { return feature_.get(); }

private:
    std::unique_ptr<Feature> feature_;
};

}  // namespace gm
