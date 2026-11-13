// C API of the mock TouchDesigner host: loads one CHOP plugin DLL and cooks it the way TouchDesigner does.
// Plain C types only (this is what ewhost.py binds with ctypes). Data layout across the API: channel-major float32,
// i.e. channel c, sample s is data[c * samples + s]. Strings are UTF-8; a returned const char* stays valid until the
// next call that can change it on the same host (document of each group below), and never needs freeing.
// Return codes of the calls that run operator code: 0 ok, 1 the operator faulted (access violation, C++ exception
// escaping the plugin, terminate, ...), 2 the operator misused the host API (asked for a parameter that does not
// exist, called an OP_Inputs function the host does not implement, declared an impossible output). The message is in
// ewh_last_error.
#pragma once
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define EWH_API __declspec(dllexport)
#define EWH_ABI_VERSION 1

typedef struct EwHost EwHost;

enum { EWH_OK = 0, EWH_OPERATOR_FAULT = 1, EWH_HOST_ERROR = 2 };

// Kinds of parameter as declared by setupParameters.
enum { EWH_PAR_FLOAT = 0, EWH_PAR_INT = 1, EWH_PAR_TOGGLE = 2, EWH_PAR_PULSE = 3, EWH_PAR_STRING = 4, EWH_PAR_MENU = 5 };

typedef struct EwParamInfo {
    int32_t kind;      // EWH_PAR_*
    int32_t size;      // number of values (1 for all the operators written so far; up to 4)
    int32_t num_menu;  // items of a menu
    int32_t reserved;
    double def[4], min[4], max[4], slider_min[4], slider_max[4];
    int32_t clamp_min[4], clamp_max[4];
} EwParamInfo;

typedef struct EwInput {
    int32_t connected;         // 0: the input slot is empty (getInputCHOP returns nullptr there)
    int32_t channels;
    int32_t samples;
    int32_t reserved;
    double sample_rate;        // <= 0: the default rate of the cook
    const float* data;         // channel-major, channels * samples floats
    const char* const* names;  // channels names, or NULL for chan1, chan2, ...
} EwInput;

typedef struct EwCookInfo {
    int32_t num_channels, num_samples;
    double sample_rate, start_index;
    int32_t timeslice;         // getGeneralInfo set timeslice
    int32_t output_declared;   // getOutputInfo returned true (the operator describes the output itself)
    int32_t input_match_index;
    int32_t cook_count;        // cooks of this instance, this one included
} EwCookInfo;

// ---- the plugin --------------------------------------------------------------------------------------------------
// Loads the DLL and creates the first instance. NULL on failure, the reason in err.
EWH_API EwHost* ewh_open(const char* dll_path, char* err, int err_len);
EWH_API void ewh_close(EwHost* host);
EWH_API int ewh_abi_version(void);
EWH_API const char* ewh_last_error(EwHost* host);
// 0 type, 1 label, 2 icon, 3 author, 4 author email
EWH_API const char* ewh_plugin_text(EwHost* host, int which);
EWH_API int ewh_plugin_inputs(EwHost* host, int* min_inputs, int* max_inputs);
// Plugin metadata: the API version the plugin reported, and the major/minor version of the custom operator.
EWH_API int ewh_plugin_version(EwHost* host, int* api_version, int* major, int* minor);

// ---- the instance ------------------------------------------------------------------------------------------------
// Destroys the node and creates a fresh one (setupParameters again, parameters at their defaults, cook count 0).
EWH_API int ewh_reset_instance(EwHost* host);

// ---- parameters (the strings stay valid until ewh_reset_instance / ewh_close) ----------------------------------------
EWH_API int ewh_param_count(EwHost* host);
EWH_API int ewh_param_info(EwHost* host, int index, EwParamInfo* info);
// 0 name, 1 label, 2 page, 3 default string (string and menu parameters: the menu item name)
EWH_API const char* ewh_param_text(EwHost* host, int index, int which);
EWH_API const char* ewh_param_menu_name(EwHost* host, int index, int item);
EWH_API const char* ewh_param_menu_label(EwHost* host, int index, int item);
// Problems found while the operator declared its parameters (invalid or duplicate name, unsupported kind, ...), one
// per line; empty when there are none.
EWH_API const char* ewh_setup_issues(EwHost* host);

// Sets a numeric / toggle parameter (clamped as TouchDesigner does), 0 on success. For a menu `value` is the item index.
EWH_API int ewh_set_number(EwHost* host, const char* name, int index, double value);
// Sets a string parameter, or a menu parameter by item name.
EWH_API int ewh_set_string(EwHost* host, const char* name, const char* value);
// Queues a pulse: pulsePressed is called at the start of the next cook.
EWH_API int ewh_pulse(EwHost* host, const char* name);
// Current value: numeric (menu: the item index) and string (menu: the item name; numbers: formatted).
EWH_API int ewh_get_number(EwHost* host, const char* name, int index, double* value);
EWH_API const char* ewh_get_string(EwHost* host, const char* name);
// 1 when the operator called enablePar(name, true) last (or never), 0 when it disabled the parameter, -1 unknown.
EWH_API int ewh_param_enabled(EwHost* host, const char* name);

// ---- cook ----------------------------------------------------------------------------------------------------------
// One cook. `default_rate` is the timeline rate (the rate of inputs and output that name none, and the FPS of
// getTimeInfo). `timeslice_samples` > 0 is the length of a timeslice; <= 0 means the length of input 0 (1 without
// input). `start_index` is the start index of the inputs and of a timeslice output. `fill` is written in the outputs
// before the cook (TouchDesigner gives unspecified memory: NaN shows what an operator did not write).
EWH_API int ewh_cook(EwHost* host, const EwInput* inputs, int num_inputs, double default_rate, int timeslice_samples,
                     double start_index, float fill);

// Gives input `index` of the NEXT cook a TOP (an image) instead of a CHOP: OP_Inputs::getInputTOP(index) returns it,
// getInputCHOP(index) returns nullptr for that slot. `data` is height rows of width pixels, rows TOP DOWN (row 0 is the top
// of the image, as a numpy array or a video frame holds it), channels interleaved: `channels` 1, 2, 3 or 4, 8-bit
// (is_float = 0, values 0-255 = 0.0-1.0) or float32 (is_float = 1, nominal 0-1). The data is copied. TouchDesigner has no
// 3-channel textures: a 3-channel image gets an opaque alpha. Native format of the texture: Mono8Fixed / RG8Fixed /
// RGBA8Fixed or Mono32Float / RG32Float / RGBA32Float. The image is dropped after the next ewh_cook. 0 ok, -1 invalid.
// The operator reads it with OP_TOPInput::downloadTexture (see README.md for formats, row order and colour).
EWH_API int ewh_set_top_input(EwHost* host, int index, const void* data, int width, int height, int channels, int is_float);

// The same for a TOP parameter (declared with appendTOP): OP_Inputs::getParTOP(name) returns the image in the next cook; a
// declared TOP parameter that was given no image gives nullptr (an empty parameter). The name must be declared.
EWH_API int ewh_set_top_par(EwHost* host, const char* name, const void* data, int width, int height, int channels, int is_float);

// Result of the last cook (valid after code 0, and after code 2 up to the failed stage).
EWH_API int ewh_result_info(EwHost* host, EwCookInfo* info);
EWH_API int ewh_result_data(EwHost* host, float* dst, int capacity);  // channel-major, floats copied
EWH_API const char* ewh_result_name(EwHost* host, int channel);
EWH_API const char* ewh_result_warning(EwHost* host);
EWH_API const char* ewh_result_error(EwHost* host);
EWH_API const char* ewh_result_popup(EwHost* host);
EWH_API int ewh_info_chop_count(EwHost* host);
EWH_API const char* ewh_info_chop_name(EwHost* host, int index);
EWH_API float ewh_info_chop_value(EwHost* host, int index);
EWH_API int ewh_info_dat_size(EwHost* host, int* rows, int* cols);  // 0: the operator has no Info DAT
EWH_API const char* ewh_info_dat_cell(EwHost* host, int row, int col);

#ifdef __cplusplus
}
#endif
