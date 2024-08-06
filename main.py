import ansys.fluent.core as pyfluent
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Union
import logging
import argparse

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class BoundaryConditionError(Exception):
    """BCs are not active, that means case is not loaded."""
    pass

class EmissivityProcessor(ABC):
    """Abstract base class for processing emissivity values."""
    @abstractmethod
    def process(self, emiss: Union[int, float, str]) -> float:
        pass

class IntEmissivityProcessor(EmissivityProcessor):
    """Processor for emissivity values given as integers."""
    def process(self, emiss: int) -> float:
        return float(emiss)
    
class FloatEmissivityProcessor(EmissivityProcessor):
    """Processor for emissivity values given as floats."""
    def process(self, emiss:float) -> float:
        return round(emiss, 3)

class NamedExpressionEmissivityProcessor(EmissivityProcessor):
    """Processor for emissivity values given as named expressions."""
    def __init__(self, solver: Any):
        self.solver = solver

    def process(self, emiss:str) -> float:
        emiss_expr = float(self.solver.setup.named_expressions[emiss].get_value())
        return round(emiss_expr, 3)

class EmissivityProcessorFactory:
    """Factory for creating appropriate EmissivityProcessor instances."""
    @staticmethod
    def create(emiss: Union[int, float, str], solver: Any) -> EmissivityProcessor:
        if isinstance(emiss, float):
            return FloatEmissivityProcessor()
        elif isinstance(emiss, int):
            return IntEmissivityProcessor()
        elif isinstance(emiss, str) and emiss in solver.setup.named_expressions:
            return NamedExpressionEmissivityProcessor(solver)
        else:
            raise ValueError("Unsupported emissivity type: ", type(emiss), " value: ", emiss)

class SolverManager:
    """Class responsible for checking atcive objects of solver"""
    def __init__(self, solver: Any):
        self.solver = solver

    def check_BCs(self) -> None:
        if not self.solver.setup.boundary_conditions.is_active():
            raise BoundaryConditionError("Load case file first.")
        
    def is_initialized(self) -> None:
        if not self.solver.results.graphics.contour.is_active():
            print("No data available.")
            return False
        return True

    def initialize(self):
        print("Initialization...")
        self.solver.solution.initialization.initialize()
        print("Initialized.")

class EmissivityManager:
    """Class responsible for managing emissivity-related operations."""
    def __init__(self, solver: Any):
        self.solver = solver
        self.e_dict: Dict[float, List[str]] = {}

    def collect_emissivities(self) -> None:
        walls = self.solver.setup.boundary_conditions.wall()
        for wall, wall_data in walls.items():
            emiss = wall_data.get('in_emiss')
            if emiss:
                processor = EmissivityProcessorFactory.create(emiss['value'],self.solver)
                emiss_value = processor.process(emiss['value'])
                logger.debug(f"{wall} has e: {emiss_value}")
                self.e_dict.setdefault(emiss_value, []).append(wall)
            else:
                logger.debug(f"{wall} doesn't partake in radiation")

    def name_emiss(self, emiss: float) -> str:
        return "e__" + str(emiss).replace(".", "_")

    def create_emissivities_cell_registers(self) -> None:
        for emiss, wall_list in self.e_dict.items():
            cr_name = self.name_emiss(emiss)
            walls_str = "(" + " ".join(wall_list) + ")"
            self.solver.tui.solve.cell_registers.add(cr_name, "type", "boundary", "boundary-list", walls_str)

    def create_emissivity_expression(self) -> None:
        def_lst = []
        overlay_lst = []
        for emiss in self.e_dict:
            cr_name = self.name_emiss(emiss)
            def_overlay = "IF(" + cr_name + ",1,0)"
            def_emiss = f"IF(AND(overlay<2,{cr_name}),{emiss},0)"
            overlay_lst.append(def_overlay)
            def_lst.append(def_emiss)
        full_def_overlay = "+".join(overlay_lst)
        full_def_emiss = "+".join(def_lst)
        # overlay is created to distinguish boundary cell registers overlapping regions
        self.solver.setup.named_expressions["overlay"] = {"definition" : full_def_overlay}
        self.solver.setup.named_expressions["emiss"] = {"definition": full_def_emiss}

class ContourPlotManager:
    """Class responsible for managing contour plots."""
    def __init__(self, solver: Any):
        self.solver = solver

    def create_contour_plot(self, e_dict: Dict[float, List[str]]) -> None:
        contour = self.solver.results.graphics.contour
        surf_disp = [surf for surfaces in e_dict.values() for surf in surfaces]
        contour["contour_emissivity"] = {
            "field": "expr:emiss",
            "filled": True,
            'surfaces_list': surf_disp,
            'coloring': {'option': 'banded', 'banded': None},
            'node_values': False,
            'color_map': {
                'size': 10,
                'size': 10,
                'color': 'sequential-black-body',
                'log_scale': False,
                'format': '%0.2f',
                'length': 0.7 ,
                'user_skip': 0},          
        }
        contour["contour_emissivity"].display()

def visualize_e(case_file: str, cores: int = 1, gui_mode: bool = False) -> None:
    solver = pyfluent.launch_fluent(
        precision="double",
        processor_count=cores,  # TODO this should be parameter in the final script
        mode="solver",
        show_gui=gui_mode
    )
    solver.file.read_case(file_name=case_file)
    
    solver_manager = SolverManager(solver)
    solver_manager.check_BCs()
    if not solver_manager.is_initialized():
        solver_manager.initialize()

    e_manager = EmissivityManager(solver)
    e_manager.collect_emissivities()
    e_manager.create_emissivities_cell_registers()
    e_manager.create_emissivity_expression()

    contour_plot_manager = ContourPlotManager(solver)
    contour_plot_manager.create_contour_plot(e_manager.e_dict)
    input("Press Enter to continue...")

def main():
    parser = argparse.ArgumentParser(description="Create emissivity contour plot in Ansys Fluent")
    
    parser.add_argument('filename', type=str, help="Case file")
    parser.add_argument('-n', '--number_of_cores', type=int, default=1, help="Number of cores (default 1)")
    parser.add_argument('-g', '--show_gui', action='store_true', help="Show Fluent GUI")
    
    args = parser.parse_args()
    filename = args.filename
    number_of_cores = args.number_of_cores
    show_gui = args.show_gui
    
    print(f"File name: {filename}")
    print(f"Number of cores: {number_of_cores}")
    print(f"Show GUI: {show_gui}")

    visualize_e(filename, number_of_cores, show_gui)

if __name__ == "__main__":
    main()
