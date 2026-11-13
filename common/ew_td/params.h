// Declaration of the parameters of an operator, without the field-by-field setup of the TouchDesigner parameter structs.
#pragma once
#include <array>
#include <cmath>
#include <limits>
#include <string>
#include <utility>
#include <vector>
#include "CPlusPlus_Common.h"

namespace ew_td {

// Limits of a numeric parameter (min, max, and whether they clamp the value) and the range of its slider, which is
// the same unless `withSlider` says otherwise.
struct Range {
    double min = 0, max = 1;
    bool clampMin = false, clampMax = false;
    double sliderMin = std::numeric_limits<double>::quiet_NaN(), sliderMax = std::numeric_limits<double>::quiet_NaN();

    static Range slider(double min, double max) { return {min, max, false, false}; }
    static Range atLeast(double min, double sliderMax) { return {min, sliderMax, true, false}; }
    static Range between(double min, double max) { return {min, max, true, true}; }

    // The same limits with another slider range, e.g. Range::atLeast(0, 10).withSlider(0.001, 1).
    Range withSlider(double lo, double hi) const {
        Range r = *this;
        r.sliderMin = lo;
        r.sliderMax = hi;
        return r;
    }
};

// The three fields of a parameter declared with `Params::vector3`.
inline std::array<double, 3> vector3(const TD::OP_Inputs* in, const char* name) {
    return {in->getParDouble(name, 0), in->getParDouble(name, 1), in->getParDouble(name, 2)};
}

class Params {
public:
    explicit Params(TD::OP_ParameterManager* manager, std::string page = "") : manager_(manager), page_(std::move(page)) {}

    // The page (tab) that the parameters declared next go to.
    Params& page(std::string page) { page_ = std::move(page); return *this; }

    void integer(const char* name, const char* label, int def, Range range) {
        TD::OP_NumericParameter p = numeric(name, label, def, range);
        manager_->appendInt(p);
    }
    void number(const char* name, const char* label, double def, Range range) {
        TD::OP_NumericParameter p = numeric(name, label, def, range);
        manager_->appendFloat(p);
    }
    // A 3D vector: one parameter with three fields (TouchDesigner shows X, Y, Z in one row). Read it with
    // `vector3(in, name)`; in Python it is `op.par.<name>x|y|z`.
    void vector3(const char* name, const char* label, const std::array<double, 3>& def, Range range) {
        TD::OP_NumericParameter p = numeric(name, label, def[0], range);
        for (int i = 0; i < 3; ++i) {
            p.defaultValues[i] = def[i];
            p.minSliders[i] = p.minSliders[0];
            p.maxSliders[i] = p.maxSliders[0];
            p.minValues[i] = p.minValues[0];
            p.maxValues[i] = p.maxValues[0];
            p.clampMins[i] = p.clampMins[0];
            p.clampMaxes[i] = p.clampMaxes[0];
        }
        manager_->appendXYZ(p);
    }
    void toggle(const char* name, const char* label, bool def) {
        TD::OP_NumericParameter p(name);
        p.label = label;
        p.page = page_.c_str();
        p.defaultValues[0] = def ? 1.0 : 0.0;
        manager_->appendToggle(p);
    }
    void string(const char* name, const char* label, const char* def) {
        TD::OP_StringParameter p(name);
        p.label = label;
        p.page = page_.c_str();
        p.defaultValue = def;
        manager_->appendString(p);
    }
    void pulse(const char* name, const char* label) {
        TD::OP_NumericParameter p(name);
        p.label = label;
        p.page = page_.c_str();
        manager_->appendPulse(p);
    }
    // A menu: `items` are (value, label) pairs; `def` is the value selected at creation.
    void menu(const char* name, const char* label, const char* def,
              const std::vector<std::pair<const char*, const char*>>& items) {
        TD::OP_StringParameter p(name);
        p.label = label;
        p.page = page_.c_str();
        p.defaultValue = def;
        std::vector<const char*> values, labels;
        for (const auto& item : items) { values.push_back(item.first); labels.push_back(item.second); }
        manager_->appendMenu(p, static_cast<int>(items.size()), values.data(), labels.data());
    }

private:
    TD::OP_NumericParameter numeric(const char* name, const char* label, double def, Range range) const {
        TD::OP_NumericParameter p(name);
        p.label = label;
        p.page = page_.c_str();
        p.defaultValues[0] = def;
        p.minSliders[0] = std::isnan(range.sliderMin) ? range.min : range.sliderMin;
        p.maxSliders[0] = std::isnan(range.sliderMax) ? range.max : range.sliderMax;
        p.minValues[0] = range.min;
        p.maxValues[0] = range.max;
        p.clampMins[0] = range.clampMin;
        p.clampMaxes[0] = range.clampMax;
        return p;
    }

    TD::OP_ParameterManager* manager_;
    std::string page_;
};

}  // namespace ew_td
