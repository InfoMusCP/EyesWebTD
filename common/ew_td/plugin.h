// The exported entry points of a CHOP plugin, from one line per operator:
//   EW_TD_CHOP(DirectnessCHOP, "Ewdirectness", "EW L2 Directness", 1, 1)
// Author name and email come from plugin_info.h and the version from the VERSION file (through the generated
// ew_td/version.h), so they are set in one place.
#pragma once
#include "CPlusPlus_Common.h"
#include "CHOP_CPlusPlusBase.h"
#include "plugin_info.h"
#include "ew_td/version.h"
#include "ew_td/chop_base.h"

namespace ew_td {
inline void fillPluginInfo(TD::CHOP_PluginInfo* info, const char* type, const char* label, int minInputs, int maxInputs) {
    if (!info->setAPIVersion(TD::CHOPCPlusPlusAPIVersion)) return;
    info->customOPInfo.opType->setString(type);
    info->customOPInfo.opLabel->setString(label);
    info->customOPInfo.authorName->setString(kAuthorName);
    info->customOPInfo.authorEmail->setString(kAuthorEmail);
    info->customOPInfo.majorVersion = kVersionMajor;
    info->customOPInfo.minorVersion = kVersionMinor;
    info->customOPInfo.minInputs = minInputs;
    info->customOPInfo.maxInputs = maxInputs;
}
}  // namespace ew_td

#define EW_TD_CHOP(ClassName, OpType, OpLabel, MinInputs, MaxInputs)                    \
    extern "C" {                                                                        \
    DLLEXPORT void FillCHOPPluginInfo(TD::CHOP_PluginInfo* info) {                      \
        ew_td::fillPluginInfo(info, OpType, OpLabel, MinInputs, MaxInputs);             \
    }                                                                                   \
    DLLEXPORT TD::CHOP_CPlusPlusBase* CreateCHOPInstance(const TD::OP_NodeInfo* info) { \
        return new ClassName(info);                                                     \
    }                                                                                   \
    DLLEXPORT void DestroyCHOPInstance(TD::CHOP_CPlusPlusBase* instance) {              \
        delete static_cast<ClassName*>(instance);                                       \
    }                                                                                   \
    }
