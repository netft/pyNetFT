#pragma once

#include <pybind11/pybind11.h>

namespace pynetft::bindings {

void bind_types(pybind11::module_ &module);

} // namespace pynetft::bindings
