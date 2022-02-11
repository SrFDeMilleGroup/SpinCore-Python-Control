import sys, os, time, configparser, traceback
import logging
import numpy as np
import re
from spinapi import *
import nidaqmx
import nidaqmx.constants as const

import PyQt5
import PyQt5.QtGui as QtGui
import PyQt5.QtWidgets as qt
import qdarkstyle

num_ch_per_board = 24 # number of TTL output channels of SpinCore PulseBlasterUSB
duration_units = ["ms", "us", "ns"] # don't change this
op_codes = ["CONTINUE", "STOP", "LOOP", "END_LOOP", "JSR", "RTS", "BRANCH", "LONG_DELAY", "WAIT"] # don't change this
bkg_color = QtGui.QColor(67, 76, 86, 127)
# daq_timeout = 10 # seconds

# convert GUI widget size in unit pt to unit px using monitor dpi
def pt_to_px(pt):
    return round(pt*monitor_dpi/72)

# a formated QGroupBox with a layout attached
class newBox(qt.QGroupBox):
    def __init__(self, layout_type="grid"):
        super().__init__()
        # self.setStyleSheet("QGroupBox {border: 0px;}")
        if layout_type == "grid":
            self.frame = qt.QGridLayout()
        elif layout_type == "vbox":
            self.frame = qt.QVBoxLayout()
        elif layout_type == "hbox":
            self.frame = qt.QHBoxLayout()
        elif layout_type == "form":
            self.frame = qt.QFormLayout()
            self.frame.setHorizontalSpacing(0)
            self.setStyleSheet("QGroupBox {border: 0px; padding-left: 0; padding-right: 0;}")
        else:
            print("newBox: layout type not supported.")
            self.frame = qt.QGridLayout()
        self.frame.setContentsMargins(0,0,0,0)
        self.setLayout(self.frame)

# a doublespinbox that won't respond if the mouse just hovers over it and scrolls the wheel,
# it will respond if it's clicked and get focus
# the purpose is to avoid accidental value change
class newDoubleSpinBox(qt.QDoubleSpinBox):
    def __init__(self, range=None, decimal=None, stepsize=1, suffix=None):
        super().__init__()
        # mouse hovering over this widget and scrolling the wheel won't bring focus into it
        # mouse can bring focus to this widget by clicking it
        self.setFocusPolicy(PyQt5.QtCore.Qt.StrongFocus)

        # scroll event and up/down button still emit valuechanged signal,
        # but typing value through keyboard only emits valuecahnged signal when enter is pressed or focus is lost
        self.setKeyboardTracking(False)

        # 0 != None
        # don't use "if not range:" statement, in case range is set to zero
        if range != None:
            self.setRange(range[0], range[1])
        if decimal != None:
            self.setDecimals(decimal)
        if stepsize != None:
            self.setSingleStep(stepsize)
        if suffix != None:
            self.setSuffix(suffix)

    # modify wheelEvent so this widget only responds when it has focus
    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            # if the event is ignored, it will be passed to and handled by parent widget
            event.ignore()

# modify SpinBox for the same reason as modifying DoubleSpinBox, see comments for newDoubleSpinBox class
class newSpinBox(qt.QSpinBox):
    def __init__(self, range=None, stepsize=1, suffix=None):
        super().__init__()
        self.setFocusPolicy(PyQt5.QtCore.Qt.StrongFocus)

        if range != None:
            self.setRange(range[0], range[1])
        if stepsize != None:
            self.setSingleStep(stepsize)
        if suffix != None:
            self.setSuffix(suffix)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()

# modify ComboBox for the same reason as modifying DoubleSpinBox, see comments for newDoubleSpinBox class
class newComboBox(qt.QComboBox):
    def __init__(self):
        super().__init__()
        self.setFocusPolicy(PyQt5.QtCore.Qt.StrongFocus)

        # self.setStyleSheet("QComboBox::down-arrow{padding-left:0px;}")
        self.setStyleSheet("QComboBox {padding:0px;}")

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()

# define the main table in GUI
class instrTable(qt.QTableWidget):
    def __init__(self, num_boards, parent):
        super().__init__(parent)
        self.parent = parent
        self.num_boards = num_boards

        self.vertical_headers_init = ["Duration", "Duration unit", "Op code", "Op data", "Note"]
        # vertical_headers = vertical_headers_init # don't use this, becasue list is passed by reference
        vertical_headers = [i for i in self.vertical_headers_init]
        for i in range(num_boards):
            for j in range(num_ch_per_board):
                vertical_headers += [f"Bd {i} Ch {j}"]

        # the number of table columns
        self.num_rows = len(vertical_headers)
        # the number of table rows
        self.num_cols = 6

        self.horizontal_headers_init = ["Note"]
        # horizontal_headers = horizontal_headers_init # don't use this, becasue list is passed by reference
        self.horizontal_headers = [i for i in self.horizontal_headers_init]
        for i in range(self.num_cols-len(self.horizontal_headers_init)):
            self.horizontal_headers += [f"Instr {i}"]

        self.setRowCount(self.num_rows)
        self.setColumnCount(self.num_cols)

        self.setVerticalHeaderLabels(vertical_headers)
        self.verticalHeader().setDefaultAlignment(PyQt5.QtCore.Qt.AlignCenter)
        self.verticalHeader().setDefaultSectionSize(25)

        self.setHorizontalHeaderLabels(self.horizontal_headers)
        self.horizontalHeader().setDefaultAlignment(PyQt5.QtCore.Qt.AlignCenter)
        self.horizontalHeader().setDefaultSectionSize(95)
        self.setColumnWidth(0, 150)
        # self.horizontalHeader().setSectionResizeMode(qt.QHeaderView.ResizeToContents)

        # a list which will save widgets from the note column
        self.note_col_widget_list = []

        # a list of dictionaries which will save widgets from each instruction column
        self.instr_col_widget_list = []

        # add widgets (mostly qt.LineEdit()) to the note column, and save them to self.note_col_widget_list
        self.add_note_col_widgets()

        for i in range(self.num_cols-len(self.horizontal_headers_init)):
            # add widgets to each instruction column, and save them in a dictionary and return it
            instr_col = self.add_instr_col_widgets(i+len(self.horizontal_headers_init))

            # add the dictionary that saves all widgets in one instruction column to self.instr_col_widget_list
            self.instr_col_widget_list.append(instr_col)

    # add widgets to the note column, and save them to self.note_col_widget_list
    def add_note_col_widgets(self):
        for i in range(len(self.vertical_headers_init)):
            la = qt.QLabel()
            la.setEnabled(False)
            
            self.setCellWidget(i, 0, la)

        for i in range(self.num_boards*num_ch_per_board):
            row_index = i + len(self.vertical_headers_init)

            le = qt.QLineEdit()
            le.setStyleSheet("QLineEdit{font: 10pt; background: transparent; border: 0px}")
            self.setCellWidget(row_index, 0, le)
            self.note_col_widget_list.append(le)

            if i%2 == 0:
                # to set table cell background color, we need to setItem first
                self.setItem(row_index, 0, qt.QTableWidgetItem())
                self.item(row_index, 0).setBackground(bkg_color)

    # add widgets to an instruction column, and save them in a dictionary and return it
    def add_instr_col_widgets(self, i):
        instr_col_widgets = {} # a dictionary that will save widgets in this instruction column and be returned

        # duration DoubleSpinBox
        du_dsb = newDoubleSpinBox(range=(0.00005, 1000000), decimal=5)
        du_dsb.setValue(10)
        du_dsb.setStyleSheet("QDoubleSpinBox{font: 10pt; border: 0px; background:transparent}")
        self.setCellWidget(0, i, du_dsb)
        instr_col_widgets["du_dsb"] = du_dsb

        # duration unit ComboBox, default is ms
        du_unit_cb = newComboBox()
        du_unit_cb.setStyleSheet("QComboBox{font: 10pt; border: 0px; background:transparent}")
        du_unit_cb.addItems(duration_units)
        du_unit_cb.currentTextChanged[str].connect(lambda val, num=i-len(self.horizontal_headers_init): self.update_du_dsb(num, val)) # if unit changes, change duration DoubleSpinBox properties accordingly
        self.setCellWidget(1, i, du_unit_cb)
        instr_col_widgets["du_unit_cb"] = du_unit_cb
        
        # op code ComboBox
        op_code_cb = newComboBox()
        op_code_cb.setStyleSheet("QComboBox{font: 10pt; border: 0px; background:transparent}")
        op_code_cb.addItems(op_codes)
        self.setCellWidget(2, i, op_code_cb)
        instr_col_widgets["op_code_cb"] = op_code_cb

        # op data SpinBox
        op_data_sb = newSpinBox(range=(0, 1000))
        op_data_sb.setStyleSheet("QSpinBox{font: 10pt; border: 0px; background:transparent}")
        self.setCellWidget(3, i, op_data_sb)
        instr_col_widgets["op_data_sb"] = op_data_sb

        # note LineEdit
        note_le = qt.QLineEdit()
        note_le.setStyleSheet("QLineEdit{font: 10pt; border: 0px; background:transparent}")
        self.setCellWidget(4, i, note_le)
        instr_col_widgets["note_le"] = note_le

        # a list which will save all radio buttons in one column
        rb_list = []

        for j in range(self.num_boards*num_ch_per_board):
            row_index = j + len(self.vertical_headers_init)
            
            rb = qt.QRadioButton()
            rb.setStyleSheet("QRadioButton{spacing:0 px}QRadioButton::indicator{width: 20px; height: 20px;}")

            # use a GroupBox to center the radio button in table cell
            box = newBox("hbox")
            # box.setStyleSheet("QGroupBox {border: 0px;}")
            box.frame.addWidget(rb)
            box.frame.setAlignment(PyQt5.QtCore.Qt.AlignCenter)
            box.setStyleSheet("border:0px; background:transparent; margin-top:0%; margin-bottom:0%;")

            self.setCellWidget(row_index, i, box)
            rb_list.append(rb)

            if j%2 == 0:
                self.setItem(row_index, i, qt.QTableWidgetItem())
                self.item(row_index, i).setBackground(bkg_color)

        instr_col_widgets["rb_list"] = rb_list

        return instr_col_widgets

    # add an instruction column to the end of the table
    def add_instr_col(self):
        self.num_cols += 1
        self.setColumnCount(self.num_cols)
        self.horizontal_headers += [f"Instr {len(self.horizontal_headers)-len(self.horizontal_headers_init)}"]
        self.setHorizontalHeaderLabels(self.horizontal_headers)

        # add widgets to this column and save them into self.instr_col_widget_list
        instr_col = self.add_instr_col_widgets(self.num_cols - len(self.horizontal_headers_init))
        self.instr_col_widget_list.append(instr_col)

        # enable del_instr_col function if there are more than one instruction column in the table
        if (self.num_cols - len(self.horizontal_headers_init) > 1) and (not self.parent.del_instr_pb.isEnabled()):
            self.parent.del_instr_pb.setEnabled(True)

    # delete the last instruction column from the table
    def del_instr_col(self):
        self.num_cols -= 1
        self.setColumnCount(self.num_cols)
        self.horizontal_headers = self.horizontal_headers[0:-1]
        # print(self.horizontal_headers)
        self.instr_col_widget_list = self.instr_col_widget_list[0:-1]

        # disable del_instr_col function if there's only one instruction column left in the table
        if self.num_cols - len(self.horizontal_headers_init) <= 1:
            self.parent.del_instr_pb.setEnabled(False)

    # read from every note column qt.LineEdit and return them
    def compile_note_col(self):
        notes = []
        for widget in self.note_col_widget_list:
            notes.append(widget.text())

        return notes

    # read values from instruction column widgets and save them in a string
    def compile_instr(self):
        num_instr = len(self.horizontal_headers) - len(self.horizontal_headers_init)

        # saves instructions for all boards
        instr_list = []
        for j in range(self.num_boards):
            instr_list_single_board = []
            for i in range(num_instr):
                # get the dictionary that saves all widgets in this instruction column
                instr_widgets = self.instr_col_widget_list[i]

                # in order of instr note, output TTL output, op code, op data, duration in unit of ns, duration in the unit specified in the table and duration unit
                instr = [0, 0, 0, 0, 0, 0, 0]
                
                # note
                instr[0] = instr_widgets["note_le"].text()
                
                # output TTL pattern
                instr[1] = 0
                for k in range(num_ch_per_board):
                    instr[1] += instr_widgets["rb_list"][k+j*num_ch_per_board].isChecked() * (2**k)

                # op code
                instr[2] = instr_widgets["op_code_cb"].currentIndex()

                # op data
                instr[3] = instr_widgets["op_data_sb"].value()

                # duration in unit of ns
                instr[4] = instr_widgets["du_dsb"].value() * (1000**(2-instr_widgets["du_unit_cb"].currentIndex()))

                # duration from its DoubleSpinBox
                instr[5] = instr_widgets["du_dsb"].value()

                # duration unit
                instr[6] = instr_widgets["du_unit_cb"].currentIndex()

                instr_list_single_board.append(instr)
            
            instr_list.append(instr_list_single_board)

        return instr_list

    # instruction column sanity check
    def instr_sanity_check(self, op_code_check, pulse_width_check):
        # I haven't used all the functions of Spincore PulseblasterUSB. Sanity check here is limited to the ones I used.

        # check op code
        if op_code_check:
            # the first instruction can't have op code WAIT
            instr_widgets = self.instr_col_widget_list[0]
            if instr_widgets["op_code_cb"].currentIndex() == 8: # 8 is WAIT
                qt.QMessageBox.warning(self, 'Setting Error',
                                    "Error: The first instruction can't have Op code WAIT.",
                                    qt.QMessageBox.Ok, qt.QMessageBox.Ok)
                return False

            # the last instruction can't have op code CONTINUE, LOOP, END_LOOP, LONG_DELAY, WAIT
            instr_widgets = self.instr_col_widget_list[-1]
            if instr_widgets["op_code_cb"].currentIndex() in [0, 2, 3, 7, 8]:
                qt.QMessageBox.warning(self, 'Setting Error',
                                    "Error: The last instruction can't have Op code CONTINUE, LOOP, END_LOOP, LONG_DELAY, or WAIT.",
                                    qt.QMessageBox.Ok, qt.QMessageBox.Ok)
                return False

        # check pulse width
        if pulse_width_check:
            # the shortest pulse width is 50 ns, and time resolution is 10 ns
            num_instr = len(self.horizontal_headers) - len(self.horizontal_headers_init)
            for i in range(num_instr):
                instr_widgets = self.instr_col_widget_list[i]
                
                # time resolution is 10 ns
                # also partially implemented in duration DoubleSpinBox settings for other units
                if instr_widgets["du_unit_cb"].currentText() == "ns":
                    du = int(instr_widgets["du_dsb"].value())
                    if du%10 != 0:
                        qt.QMessageBox.warning(self, 'Setting Error',
                                    f"Error (Instr {i}): The Spincore PulseblasterUSB time resolution is 10 ns.",
                                    qt.QMessageBox.Ok, qt.QMessageBox.Ok)
                        return False

                # the shortest acceptable pulse width is 50 ns
                duration = instr_widgets["du_dsb"].value() * (1000**(2-instr_widgets["du_unit_cb"].currentIndex()))
                if duration < 50:
                    qt.QMessageBox.warning(self, 'Setting Error',
                                    f"Error (Instr {i}): The shortest acceptable pulse width is 50 ns.",
                                    qt.QMessageBox.Ok, qt.QMessageBox.Ok)
                    return False

        return True

    # update duration DoubleSpinBox settings if duration unit changes
    def update_du_dsb(self, num, val):
        if val == "ms":
            instr_widgets = self.instr_col_widget_list[num]
            instr_widgets["du_dsb"].setDecimals(5) # time resolution is 10 ns
            instr_widgets["du_dsb"].setMinimum(0.00005) # 50 ns
            instr_widgets["du_dsb"].setSingleStep(1)

        elif val == "us":
            instr_widgets = self.instr_col_widget_list[num]
            instr_widgets["du_dsb"].setDecimals(2) # time resolution is 10 ns
            instr_widgets["du_dsb"].setMinimum(0.05) # 50 ns
            instr_widgets["du_dsb"].setSingleStep(1)
        
        elif val == "ns":
            instr_widgets = self.instr_col_widget_list[num]
            instr_widgets["du_dsb"].setDecimals(0) # time resolution is 10 ns
            instr_widgets["du_dsb"].setMinimum(50) # 50 ns
            instr_widgets["du_dsb"].setSingleStep(10)

        else:
            print("Unsupported duration unit: {val}.")

    # clear some widgets' values in the table 
    def clear_columns(self):
        # clear notes column
        for widget in self.note_col_widget_list:
            widget.setText("")

        # clear radiobuttons in instruction columns
        for instr_dict in self.instr_col_widget_list:
            rb_list = instr_dict["rb_list"]
            for rb in rb_list:
                rb.setChecked(False)
    
    # load parameters from a local configuration file
    # row numbers won't change, extra rows will be left empty or only first certain number of boards will be loaded
    # restart the program to re-detect number of boards if it needed
    def load_config(self, config):
        new_num_boards = int(config["General settings"]["number of boards"])
        new_num_boards = min(new_num_boards, self.num_boards)
        num_instr = int(config["General settings"]["number of instructions"])

        # usually widgets values in the table will just be overwritten, 
        # but in the case of board number change, some widgets can be left unchanged.
        # Their values need to be explicitly cleared.
        self.clear_columns() 

        # adjust row number
        while num_instr+len(self.horizontal_headers_init) < self.num_cols:
            self.del_instr_col()

        while num_instr+len(self.horizontal_headers_init) > self.num_cols:
            self.add_instr_col()

        # update note column
        for i in range(new_num_boards):
            for j in range(num_ch_per_board):
                widget = self.note_col_widget_list[i*num_ch_per_board+j]
                connections = [x.strip() for x in config["General settings"][f"board {i} connections"].split(",")][::-1]
                widget.setText(connections[j])
                widget.setCursorPosition(0)

        # update instruction columns
        for i in range(num_instr):
            instr_dict = self.instr_col_widget_list[i]
            instr_dict["note_le"].setText(config[f"Instr {i}"]["instr note"])
            instr_dict["note_le"].setCursorPosition(0)
            instr_dict["du_unit_cb"].setCurrentText(config[f"Instr {i}"]["duration unit"]) # put this step before updating du_dsb, in case it changes du_dsb decimal setting
            instr_dict["du_dsb"].setValue(float(config[f"Instr {i}"]["duration time"]))
            instr_dict["op_code_cb"].setCurrentText(config[f"Instr {i}"]["op code"])
            instr_dict["op_data_sb"].setValue(int(config[f"Instr {i}"]["op data"]))

            # update radio buttons
            for j in range(new_num_boards):
                ttl = config[f"Instr {i}"][f"board {j} ttl output pattern"][2:][::-1]
                for k in range(num_ch_per_board):
                    rb = instr_dict["rb_list"][j*num_ch_per_board+k]
                    rb.setChecked(bool(int(ttl[k])))

# define the table in scanner
class scannerTable(qt.QTableWidget):
    def __init__(self, parent):
        super().__init__()
        self.parent = parent

        vertical_headers_init = ["Instr #", "Start Duration", "Start Unit", "End Duration", "End Unit"]

        # number of rows
        self.num_rows = len(vertical_headers_init)
        # number of columns
        self.num_cols = 2

        self.horizontal_headers = []
        for i in range(self.num_cols):
            self.horizontal_headers.append(f"Scan Instr {i}")

        self.setRowCount(self.num_rows)
        self.setColumnCount(self.num_cols)

        self.setVerticalHeaderLabels(vertical_headers_init)
        self.verticalHeader().setDefaultAlignment(PyQt5.QtCore.Qt.AlignCenter)
        self.verticalHeader().setDefaultSectionSize(25)

        self.setHorizontalHeaderLabels(self.horizontal_headers)
        self.horizontalHeader().setDefaultSectionSize(95)

        # a list of dictionaries which save widgets from each column 
        self.col_widget_list = []
        for i in range(self.num_cols):
            self.col_widget_list.append(self.add_col_widgets(i))

    # add widgets to a column
    def add_col_widgets(self, i):
        col_widgets = {} # dictionary that will save all widgets in this column, and be returned

        # instruction column number in the main table
        instr_num_sb = newSpinBox(range=(0, 100000))
        instr_num_sb.setStyleSheet("QSpinBox{font: 9pt; border: 0px; background:transparent}")
        self.setCellWidget(0, i, instr_num_sb)
        col_widgets["instr_num_sb"] = instr_num_sb

        # start duration DoubleSpinBox
        start_du_dsb = newDoubleSpinBox(range=(0.00005, 1000000), decimal=5)
        start_du_dsb.setValue(10)
        start_du_dsb.setStyleSheet("QDoubleSpinBox{font: 9pt; border: 0px; background:transparent}")
        self.setCellWidget(1, i, start_du_dsb)
        col_widgets["start_du_dsb"] = start_du_dsb

        # start duration unit ComboBox
        start_du_unit_cb = newComboBox()
        start_du_unit_cb.setStyleSheet("QComboBox{font: 9pt; border: 0px; background:transparent}")
        start_du_unit_cb.addItems(duration_units)
        start_du_unit_cb.currentTextChanged[str].connect(lambda val, num=i, type="start": self.update_du_dsb(num, val, type)) # change the duration DoubleSpinBox properties when unit changes
        self.setCellWidget(2, i, start_du_unit_cb)
        col_widgets["start_du_unit_cb"] = start_du_unit_cb

        # end suration DoubleSpinBox
        end_du_dsb = newDoubleSpinBox(range=(0.00005, 1000000), decimal=5)
        end_du_dsb.setValue(10)
        end_du_dsb.setStyleSheet("QDoubleSpinBox{font: 9pt; border: 0px; background:transparent}")
        self.setCellWidget(3, i, end_du_dsb)
        col_widgets["end_du_dsb"] = end_du_dsb

        # end duration unit ComboBox
        end_du_unit_cb = newComboBox()
        end_du_unit_cb.setStyleSheet("QComboBox{font: 9pt; border: 0px; background:transparent}")
        end_du_unit_cb.addItems(duration_units)
        end_du_unit_cb.currentTextChanged[str].connect(lambda val, num=i, type="end": self.update_du_dsb(num, val, type)) # change the duration DoubleSpinBox properties when unit changes
        self.setCellWidget(4, i, end_du_unit_cb)
        col_widgets["end_du_unit_cb"] = end_du_unit_cb

        return col_widgets

    # add a column to the end of the table
    def add_col(self):
        self.num_cols += 1
        self.setColumnCount(self.num_cols)

        self.horizontal_headers.append(f"Scan Instr {self.num_cols-1}")
        self.setHorizontalHeaderLabels(self.horizontal_headers)

        # add widgets to this column
        self.col_widget_list.append(self.add_col_widgets(self.num_cols-1))

        # enable del_scan_instr function when there are more than one column in the table
        if (self.num_cols > 1) and (not self.parent.del_scan_instr_pb.isEnabled()):
            self.parent.del_scan_instr_pb.setEnabled(True)

    # delete the last column from the table
    def del_col(self):
        self.num_cols -= 1
        self.setColumnCount(self.num_cols)
        self.horizontal_headers = self.horizontal_headers[0:-1]
        self.col_widget_list = self.col_widget_list[0:-1]

        # disable del_scan_instr funtion if there's only one column left
        if self.num_cols <= 1:
            self.parent.del_scan_instr_pb.setEnabled(False)

    # update duration DoubleSpinBox properties when duration unit changes 
    def update_du_dsb(self, num, val, type):
        if type == "start":
            widget = self.col_widget_list[num]["start_du_dsb"]
        elif type == "end":
            widget = self.col_widget_list[num]["end_du_dsb"]
        else:
            print("Unsupported type.")
            return

        if val == "ms":
            widget.setDecimals(5) # time resolution is 10 ns
            widget.setMinimum(0.00005) # 50 ns
            widget.setSingleStep(1)
        elif val == "us":
            widget.setDecimals(2) # time resolution is 10 ns
            widget.setMinimum(0.05) # 50 ns
            widget.setSingleStep(1)
        elif val == "ns":
            widget.setDecimals(0) # time resolution is 10 ns
            widget.setMinimum(50) # 50 ns
            widget.setSingleStep(10)
        else:
            print("Unsupported duration unit: {val}.")

    # read values from each widgets and save them in a list, and return it
    def compile_scan_instr(self):
        scan_instr_list = []
        for i in range(self.num_cols):
            scan_instr = {}
            col_widgets = self.col_widget_list[i]
            scan_instr["instr no."] = str(col_widgets["instr_num_sb"].value())
            scan_instr["start duration time"] = str(col_widgets["start_du_dsb"].value())
            scan_instr["start duration unit"] = col_widgets["start_du_unit_cb"].currentText()
            scan_instr["end duration time"] = str(col_widgets["end_du_dsb"].value())
            scan_instr["end duration unit"] = col_widgets["end_du_unit_cb"].currentText()

            scan_instr_list.append(scan_instr)

        return scan_instr_list

    # load parameters from local configuration file
    def load_config(self, config):
        new_num_cols = config.getint("Scanner settings", "number of scan instr")

        # adjust column number the one specified in the configuration file
        while new_num_cols > self.num_cols:
            self.add_col()

        while new_num_cols < self.num_cols:
            self.del_col()

        # update values of widgets 
        for i in range(new_num_cols):
            col_widgets = self.col_widget_list[i]
            col_widgets["instr_num_sb"].setValue(config.getint(f"Scan Instr {i}", "instr no."))
            col_widgets["start_du_dsb"].setValue(config.getfloat(f"Scan Instr {i}", "start duration time"))
            col_widgets["start_du_unit_cb"].setCurrentText(config[f"Scan Instr {i}"]["start duration unit"])
            col_widgets["end_du_dsb"].setValue(config.getfloat(f"Scan Instr {i}", "end duration time"))
            col_widgets["end_du_unit_cb"].setCurrentText(config[f"Scan Instr {i}"]["end duration unit"])

    # scanner table sanity check
    def scan_instr_sanity_check(self):
        for i in range(self.num_cols):
            col_widgets = self.col_widget_list[i]
            instr_num = col_widgets["instr_num_sb"].value()
            if instr_num > (self.parent.parent.table.num_cols - len(self.parent.parent.table.horizontal_headers_init)-1):
                qt.QMessageBox.warning(self, 'Scanner Setting Error',
                                f"Error (Scan Instr {i}): Instr # doesn't exist.",
                                qt.QMessageBox.Ok, qt.QMessageBox.Ok)
                return False

            # the shortest pulse width is 50 ns
            start_duration = col_widgets["start_du_dsb"].value() * (1000**(2-col_widgets["start_du_unit_cb"].currentIndex()))
            if start_duration < 50:
                qt.QMessageBox.warning(self, 'Scanner Setting Error',
                                f"Error (Scan Instr {i}): The shortest acceptable pulse width is 50 ns.",
                                qt.QMessageBox.Ok, qt.QMessageBox.Ok)
                return False

            # time resolution is 10 ns
            # also partially implemented in duration DoubleSpinBox settings for other units
            if col_widgets["start_du_unit_cb"].currentText() == "ns":
                du = int(col_widgets["start_du_dsb"].value())
                if du%10 != 0:
                    qt.QMessageBox.warning(self, 'Scanner Setting Error',
                                f"Error (Scan Instr {i}): The Spincore PulseblasterUSB time resolution is 10 ns.",
                                qt.QMessageBox.Ok, qt.QMessageBox.Ok)
                    return False

            # the shortest pulse width is 50 ns
            end_duration = col_widgets["end_du_dsb"].value() * (1000**(2-col_widgets["end_du_unit_cb"].currentIndex()))
            if end_duration < 50:
                qt.QMessageBox.warning(self, 'Scanner Setting Error',
                                f"Error (Scan Instr {i}): The shortest acceptable pulse width is 50 ns.",
                                qt.QMessageBox.Ok, qt.QMessageBox.Ok)
                return False

            # time resolution is 10 ns
            # also partially implemented in duration DoubleSpinBox settings for other units
            if col_widgets["end_du_unit_cb"].currentText() == "ns":
                du = int(col_widgets["end_du_dsb"].value())
                if du%10 != 0:
                    qt.QMessageBox.warning(self, 'Scanner Setting Error',
                                f"Error (Scan Instr {i}): The Spincore PulseblasterUSB time resolution is 10 ns.",
                                qt.QMessageBox.Ok, qt.QMessageBox.Ok)
                    return False

        return True

    # generate scan sequence
    def generate_sequence(self, randomize):
        scan_sequence_list = []
        samp_num = self.parent.samp_num_sb.value()
        rep_num = self.parent.rep_num_sb.value()
        for i in range(self.num_cols):
            col_widgets = self.col_widget_list[i]
            scan_sequence = {}
            scan_sequence["instr no."] = col_widgets["instr_num_sb"].value()
            scan_start = col_widgets["start_du_dsb"].value() * (1000**(2-col_widgets["start_du_unit_cb"].currentIndex())) # start duration time to scan 
            scan_end = col_widgets["end_du_dsb"].value() * (1000**(2-col_widgets["end_du_unit_cb"].currentIndex())) # end suration time to scan
            seq = np.linspace(scan_start, scan_end, samp_num) # linearly sample from start to end 
            seq = np.tile(seq, rep_num) # use np.tile to get [1, 2, 3, 1, 2, 3], use np.repeat to get [1, 1, 2, 2, 3, 3]
            scan_sequence["sequence"] = seq

            scan_sequence_list.append(scan_sequence)

        # if the sequence needs to be randomized
        if randomize:
            total_num = samp_num*rep_num
            random_index = np.arange(total_num)
            np.random.shuffle(random_index)
            # print(random_index)

            for i in range(self.num_cols):
                scan_sequence_list[i]["sequence"] = scan_sequence_list[i]["sequence"][random_index]

        return scan_sequence_list        

# a GroupBox to place scanner widgets
class scannerBox(newBox):
    def __init__(self, parent):
        super().__init__(layout_type="grid")
        self.parent = parent
        self.setTitle("Scanner")
        self.setStyleSheet("QGroupBox{border-width: 1px; padding-top: 16px; font:13pt}QPushButton{font: 9pt}QLabel{font: 9pt}QLineEdit{font: 9pt}QCheckBox{font: 9pt}")
        self.frame.setColumnStretch(0, 6)
        self.frame.setColumnStretch(1, 5)
        self.frame.setColumnStretch(2, 5)
        self.frame.setColumnStretch(3, 5)
        self.frame.setColumnStretch(4, 5)
        self.setMaximumHeight(290)

        self.random_seq = True # to randomize scan sequence or not
        self.scanning = False # is the program currently scanning

        # place all widgets except the table
        self.place_controls()

        # place the table
        self.table = scannerTable(self)
        self.frame.addWidget(self.table, 4, 1, 1, 4)

    # place widgets in the scanner GroupBox
    def place_controls(self):
        self.progress_bar = qt.QProgressBar()
        self.frame.addWidget(self.progress_bar, 0, 0)
        self.progress_bar.setValue(0)

        operating_procedure = "Operating procedure:\n\n\n"
        operating_procedure += "0. A WAIT...BRANCH structure is needed.\n\n"
        operating_procedure += "1. Turn off PulseBlaster external trigger.\n\n"
        operating_procedure += "2. Click the \"Scan\" button.\n\n"
        operating_procedure += f"3. Turn on PulseBlaster external trigger."

        la = qt.QLabel(operating_procedure)
        la.setStyleSheet("QLabel{background: rgba(67, 76, 86, 127); font:9 pt}")
        self.frame.addWidget(la, 1, 0, 4, 1)

        # a pushbutton to add scan instruction
        self.add_scan_instr_pb = qt.QPushButton("Add Scan Instr")
        self.add_scan_instr_pb.clicked[bool].connect(lambda val:self.table.add_col())
        self.frame.addWidget(self.add_scan_instr_pb, 0, 1)

        # a pushbutton to delete scan instruction
        self.del_scan_instr_pb = qt.QPushButton("Del Scan Instr")
        self.del_scan_instr_pb.clicked[bool].connect(lambda val:self.table.del_col())
        self.frame.addWidget(self.del_scan_instr_pb, 0, 2)

        # a pushbutton to start scanning
        self.scan_pb = qt.QPushButton("Scan")
        self.scan_pb.clicked[bool].connect(lambda val:self.scan())
        self.frame.addWidget(self.scan_pb, 0, 3)

        # a pushbutton to stop scanning
        self.stop_scan_pb = qt.QPushButton("Stop Scan")
        self.stop_scan_pb.clicked[bool].connect(lambda val:self.stop_scan())
        self.stop_scan_pb.setEnabled(False)
        self.frame.addWidget(self.stop_scan_pb, 0, 4)

        self.frame.addWidget(qt.QLabel("Sample Number:"), 1, 1, alignment=PyQt5.QtCore.Qt.AlignRight)

        # sample number SpinBox
        self.samp_num_sb = newSpinBox(range=(2, 100000))
        self.samp_num_sb.setValue(10)
        self.frame.addWidget(self.samp_num_sb, 1, 2)

        self.frame.addWidget(qt.QLabel("Repetition Number:"), 1, 3, alignment=PyQt5.QtCore.Qt.AlignRight)

        # repetition number SpinBox
        self.rep_num_sb = newSpinBox(range=(1, 100000))
        self.rep_num_sb.setValue(10)
        self.frame.addWidget(self.rep_num_sb, 1, 4)

        self.frame.addWidget(qt.QLabel("Sequence Name to Save:"), 2, 1, alignment=PyQt5.QtCore.Qt.AlignRight)

        # a LineEdit to indicate the file name to save sequence
        self.seq_name_le = qt.QLineEdit("Scan_sequence")
        self.frame.addWidget(self.seq_name_le, 2, 2)

        self.frame.addWidget(qt.QLabel("DAQ DI Channel:"), 2, 3, alignment=PyQt5.QtCore.Qt.AlignRight)

        # a LineEdit to indicate DAQ DI cahnnel
        self.daq_ch_le = qt.QLineEdit("Dev_/port_/line_")
        self.frame.addWidget(self.daq_ch_le, 2, 4)

        # a checkbox to indicate whether to append date/time to the filename when a sequence is saved
        self.auto_append_chb = qt.QCheckBox("Auto Append Date/Time")
        self.auto_append_chb.setChecked(True)
        self.frame.addWidget(self.auto_append_chb, 3, 2)

        # a checkbox to indicate whether to randomize scan sequence
        self.random_chb = qt.QCheckBox("Randomize Sequence")
        self.random_chb.setChecked(self.random_seq)
        self.random_chb.toggled[bool].connect(lambda val: self.update_random_chb(val))
        self.frame.addWidget(self.random_chb, 3, 4)

    # change the value of variable "self.random_seq"
    def update_random_chb(self, val):
        self.random_seq = val

    # laod parameters from a local configuration file
    def load_config(self, config):
        self.samp_num_sb.setValue(config.getint("Scanner settings", "sample number"))
        self.rep_num_sb.setValue(config.getint("Scanner settings", "repetition number"))
        self.random_chb.setChecked(config.getboolean("Scanner settings", "randomize sequence"))
        self.daq_ch_le.setText(config.get("Scanner settings", "DAQ DI channel"))

        self.table.load_config(config)

    # start to scan parameters
    def scan(self):
        # perform sanity checks
        if not self.table.scan_instr_sanity_check():
            return

        if not self.parent.table.instr_sanity_check(op_code_check=True, pulse_width_check=True):
            return

        if not self.daq_sanity_check():
            return

        # disable or enable some widgets
        self.enable_widgets(False)
        self.stop_scan_pb.setEnabled(True)
        self.scanning = True

        # generate scan sequence
        self.scan_sequence_list = self.table.generate_sequence(self.random_seq)
        # print(self.scan_sequence_list)
        self.counter = 0
        self.scan_sequence_len = len(self.scan_sequence_list[0]["sequence"])
        self.scan_instr_num = len(self.scan_sequence_list)

        # save scan sequence to a local file
        saved = self.save_sequence()
        if not saved:
            self.enable_widgets(True)
            self.stop_scan_pb.setEnabled(False)
            self.scanning = False
            return

        # stop, reset and restart PulseBlaster
        for i in range(self.parent.num_boards):
            pb_select_board(i)
            pb_stop()
            pb_reset()

            # start spincore and make it ready to be triggered
            pb_start()

        # load the first scan parameter to PulseBlaster
        self.load_param()

        # a DAQ is used to read Spincore "WAITING" signal, a rising edge will be used to trigger loading
        self.task = nidaqmx.Task("DI task")
        ch = self.daq_ch_le.text()
        self.task.di_channels.add_di_chan(ch)
        self.task.timing.cfg_change_detection_timing(rising_edge_chan=ch,
                                                    sample_mode=const.AcquisitionType.CONTINUOUS
                                                    )
        # see https://nidaqmx-python.readthedocs.io/en/latest/task.html for an example of the callback method
        self.task.register_signal_event(const.Signal.CHANGE_DETECTION_EVENT, self.load_param)

        self.task.start()

    # stop scanning
    def stop_scan(self):
        # stop and close DAQ task
        try:
            self.task.stop()
            self.task.close()
        except Exception as err:
            print(err)
            logging.warning(err)

        self.enable_widgets(True)
        self.stop_scan_pb.setEnabled(False)
        self.scanning = False

        time.sleep(0.1) # for some reason we need this step here otherwise the next line will crash the program
        self.progress_bar.setValue(0)

    # enable or disable widgets
    def enable_widgets(self, en):
        self.parent.add_instr_pb.setEnabled(en)
        self.parent.del_instr_pb.setEnabled(en)
        self.parent.toggle_scanner_pb.setEnabled(en)
        self.parent.soft_trig_pb.setEnabled(en)
        self.parent.load_board_pb.setEnabled(en)
        self.parent.save_config_pb.setEnabled(en)
        self.parent.load_config_pb.setEnabled(en)

        self.parent.table.setEnabled(en)

        self.add_scan_instr_pb.setEnabled(en)
        self.del_scan_instr_pb.setEnabled(en)
        self.scan_pb.setEnabled(en)
        self.samp_num_sb.setEnabled(en)
        self.rep_num_sb.setEnabled(en)
        self.seq_name_le.setEnabled(en)
        self.daq_ch_le.setEnabled(en)
        self.auto_append_chb.setEnabled(en)
        self.random_chb.setEnabled(en)
        self.table.setEnabled(en)

    # save sequence locally, it's necessary when the sequence is randomized
    def save_sequence(self):
        # compile a file name to save
        filename = self.seq_name_le.text()
        if self.auto_append_chb.isChecked():
            filename += "_"
            filename += time.strftime("%Y%m%d_%H%M%S")
        filename += ".ini"
        filename = r"saved_sequences/" + filename

        # check if the file name exists and whether to overwrite
        if os.path.exists(filename):
            overwrite = qt.QMessageBox.warning(self, 'Sequence file name exists',
                                            'Sequence file name already exists. Continue to overwrite it?',
                                            qt.QMessageBox.Yes | qt.QMessageBox.No,
                                            qt.QMessageBox.No)
            if overwrite == qt.QMessageBox.No:
                return False

        # check if the directory exists, create it if not
        dir_name = os.path.dirname(filename)
        if not os.path.exists(dir_name):
            os.mkdir(dir_name)

        # create the config, its format should be readable by the camera program 
        config = configparser.ConfigParser()
        config.optionxform = str

        config["Settings"] = {}
        samp_num = self.samp_num_sb.value()
        rep_num = self.rep_num_sb.value()
        config["Settings"]["sample number"] = str(samp_num)
        config["Settings"]["repetition number"] = str(rep_num)
        config["Settings"]["element number"] = str(samp_num*rep_num)
        config["Settings"]["scan device"] = "PulseBlasterUSB"
        instr_num = self.scan_sequence_list[0]["instr no."]
        config["Settings"]["scan param"] = f"instr no. {instr_num}"
        for i in range(self.scan_sequence_len):
            config[f"Sequence element {i}"] = {}
            for j in range(self.scan_instr_num):
                instr_num = self.scan_sequence_list[j]["instr no."]
                val = self.scan_sequence_list[j]["sequence"][i]
                config[f"Sequence element {i}"][f"PulseBlasterUSB [instr no. {instr_num} (ns)]"] = str(val)
        configfile = open(filename, "w")
        config.write(configfile)
        configfile.close()

        # save scan sequence to camera folder, so the camera program can read it
		# configfile = open(r"C:\Users\BufferLab\Desktop\Python-Lab-Control\pixelfly-python-control\scan_sequence\latest_sequence.ini", "w")
		# config.write(configfile)
		# configfile.close()

        return True

    # DAQ channel sanity check
    def daq_sanity_check(self):
        daq_ch = self.daq_ch_le.text()
        daq_ch = daq_ch.strip()

        # check whether the channel name is legitimate
        matched = re.match("Dev[0-9]{1,}/port[0-9]{1,}/line[0-9]{1,}", daq_ch)
        is_matched = bool(matched)
        if not is_matched:
            qt.QMessageBox.warning(self, 'DAQ Channel Error',
                                f"Error: DAQ channel name ({daq_ch}) can't be recognized.",
                                qt.QMessageBox.Ok, qt.QMessageBox.Ok)
            return False

        # check whether the channel exists in this computer
        di_channels = []
        dev_collect = nidaqmx.system._collections.device_collection.DeviceCollection()
        for i in dev_collect.device_names:
            ch_collect = nidaqmx.system._collections.physical_channel_collection.DILinesCollection(i)
            for j in ch_collect.channel_names:
                di_channels.append(j)
        if daq_ch not in di_channels:
            qt.QMessageBox.warning(self, 'DAQ Channel Error',
                                f"Error: Specified DAQ channel ({daq_ch}) doesn't exist in this computer.",
                                qt.QMessageBox.Ok, qt.QMessageBox.Ok)
            return False

        return True

    # load parameters into PulseBlaster. Will be called in every cycle
    def load_param(self, task_handle=None, signal_type=None, callback_date=None):
        time.sleep(0.02) # seconds, important in the case of trigger signal has oscillations at rising/falling edge

        if self.counter < self.scan_sequence_len:
            for i in range(self.scan_instr_num):
                j = self.scan_sequence_list[i]["instr no."]
                instr_col_widgets = self.parent.table.instr_col_widget_list[j] # find the instruction column desired to scan
                unit = instr_col_widgets["du_unit_cb"].currentIndex()
                du = self.scan_sequence_list[i]["sequence"][self.counter]
                du = du/(1000**(2-unit))
                # print(du)
                instr_col_widgets["du_dsb"].setValue(du) # update duration DoubleSpinBox value

            # copmile instructions and load to boards
            self.parent.load_board(perform_sanity_check=False)

            self.progress_bar.setValue(int(self.counter/self.scan_sequence_len*100.0))
            self.counter += 1

        # scanning finishes
        elif self.counter == self.scan_sequence_len:
            self.stop_scan()            
        
        # return an int is necessary for DAQ callback function
        return 0
        
# main window
class mainWindow(qt.QMainWindow):
    def __init__(self, app):
        super().__init__()

        self.num_boards = self.init_spincore()
        # self.num_boards = 2

        self.box = newBox(layout_type="grid")
        self.box.setStyleSheet("QGroupBox{border-width: 0 px;}")
        
        # the top GroupBox in the main window, which contains multiple control widgets
        ctrl_box = self.place_controls()
        self.box.frame.addWidget(ctrl_box, 0, 0)

        # scanner box
        self.scan_box = scannerBox(self)
        self.box.frame.addWidget(self.scan_box, 1, 0)
        # self.scan_box.hide()

        # main table
        self.table = instrTable(self.num_boards, self)
        self.box.frame.addWidget(self.table, 2, 0)

        self.setCentralWidget(self.box)
        self.resize(pt_to_px(700), pt_to_px(900))
        self.setWindowTitle("PulseBlasterUSB Timing Control")
        self.show()

    # initialize Spincore PulseBlaster boards
    def init_spincore(self):
		# Downloaded form http://www.spincore.com/support/SpinAPI_Python_Wrapper/Python_Wrapper_Main.shtml and modified
		# Enable the SpinCore log file
        pb_set_debug(1)

        num_board = pb_count_boards()

        print(f"\n\nUsing SpinAPI Library version {pb_get_version()}")
        print(f"Found {num_board} board(s) in the system.")
        print("This program controls the TTL outputs of the PulseBlasterUSB.\n")

        if num_board == 0:
            return num_board

        # initialize every board
        for i in range(num_board):
            pb_select_board(i)

            # pb_init() function has to be called before any programming/start/stop instructions
            if pb_init() != 0:
                print("Error initializing board: %s" % pb_get_error())
                input("Please press a key to continue.")
                exit(-1)

            # Configure the core clock, in MHz
            pb_core_clock(100.0)

        return num_board

    # place control widgets in the ctrl_box
    def place_controls(self):
        ctrl_box = newBox("grid")
        ctrl_box.setTitle("General Control")
        ctrl_box.setStyleSheet("QGroupBox{border-width: 1px; padding-top: 16px; font:13pt}QPushButton{font: 10pt}QLabel{font: 10pt}QLineEdit{font: 10pt}QCheckBox{font: 10pt}")
        ctrl_box.frame.setColumnStretch(0, 1)
        ctrl_box.frame.setColumnStretch(1, 1)
        ctrl_box.frame.setColumnStretch(2, 1)
        ctrl_box.frame.setColumnStretch(3, 1)
        ctrl_box.frame.setColumnStretch(4, 1)

        # a pushbutton to add an instruction column
        self.add_instr_pb = qt.QPushButton("Add Instr")
        self.add_instr_pb.clicked[bool].connect(lambda val:self.table.add_instr_col())
        ctrl_box.frame.addWidget(self.add_instr_pb, 0, 0)

        # a pushbutton to delete an instruction column
        self.del_instr_pb = qt.QPushButton("Del Instr")
        self.del_instr_pb.clicked[bool].connect(lambda val:self.table.del_instr_col())
        ctrl_box.frame.addWidget(self.del_instr_pb, 0, 1)

        # a pushbutton to show or hide scanner widgets
        self.toggle_scanner_pb = qt.QPushButton("Toggle Scanner")
        self.toggle_scanner_pb.clicked[bool].connect(lambda val:self.toggle_scanner())
        ctrl_box.frame.addWidget(self.toggle_scanner_pb, 0, 2)

        # a pushbutton to trigger boards once
        self.soft_trig_pb = qt.QPushButton("Software Trig")
        self.soft_trig_pb.clicked[bool].connect(lambda val:self.software_trigger())
        self.soft_trig_pb.setToolTip("Caveat: this doesn't sync multiple boards.")
        ctrl_box.frame.addWidget(self.soft_trig_pb, 0, 3)

        # a pushbutton to load parameters into boards
        self.load_board_pb = qt.QPushButton("Load Boards")
        self.load_board_pb.clicked[bool].connect(lambda val, perform_sanity_check=True:self.load_board(perform_sanity_check))
        ctrl_box.frame.addWidget(self.load_board_pb, 0, 4)

        ctrl_box.frame.addWidget(qt.QLabel("File Name to Save:"), 1, 0, alignment=PyQt5.QtCore.Qt.AlignRight)

        # a LineEdit to indicate file name to save configurations
        self.filename_le = qt.QLineEdit("PulseBlasterUSB_configs")
        ctrl_box.frame.addWidget(self.filename_le, 1, 1)

        # a checkbox to indicate whether to append date/time to the configuration file name
        self.auto_append_chb = qt.QCheckBox("Auto Append Date/Time")
        self.auto_append_chb.setChecked(True)
        ctrl_box.frame.addWidget(self.auto_append_chb, 1, 2)

        # a pushbutton to compile and save configuration locally
        self.save_config_pb = qt.QPushButton("Save Config")
        self.save_config_pb.clicked[bool].connect(lambda val:self.save_config())
        ctrl_box.frame.addWidget(self.save_config_pb, 1, 3)

        # a pushbutton to load parameters from a local configuration file
        self.load_config_pb = qt.QPushButton("Load Config")
        self.load_config_pb.clicked[bool].connect(lambda val:self.load_config())
        ctrl_box.frame.addWidget(self.load_config_pb, 1, 4)

        return ctrl_box

    # load parameters to PulseBlaster boards
    def load_board(self, perform_sanity_check):
        # perform sanity check
        if perform_sanity_check:
            if not self.table.instr_sanity_check(op_code_check=True, pulse_width_check=True):
                return

        # compie instructions from the main table
        instr_list = self.table.compile_instr()

        # write instructions to boards
        for j, instr_single_board in enumerate(instr_list):
            pb_select_board(j)
            pb_start_programming(PULSE_PROGRAM)
            for i in range(len(instr_single_board)):
                instr = instr_single_board[i]
                pb_inst_pbonly(*instr[1:5])
            pb_stop_programming()

        # for j, instr_single_board in enumerate(instr_list):
        #     for i in range(len(instr_single_board)):
        #         print(instr_single_board[i])

    # hide or show scanner widgets  
    def toggle_scanner(self):
        if self.scan_box.isVisible():
            self.scan_box.hide()
        else:
            self.scan_box.show()

    # trigger PulseBlaster boards
    def software_trigger(self):
        # multiple boards won't be trigger at the same time
        for i in range(self.num_boards):
            pb_select_board(i)
            pb_start()

    # save configurations to a local file
    def save_config(self):
        # compile file name to save
        filename = self.filename_le.text()
        if self.auto_append_chb.isChecked():
            filename += "_"
            filename += time.strftime("%Y%m%d_%H%M%S")
        filename += ".ini"
        filename = r"saved_configs/" + filename

        # check if the file name exists and whether to overwrite
        if os.path.exists(filename):
            overwrite = qt.QMessageBox.warning(self, 'File name exists',
                                            'File name already exists. Continue to overwrite it?',
                                            qt.QMessageBox.Yes | qt.QMessageBox.No,
                                            qt.QMessageBox.No)
            if overwrite == qt.QMessageBox.No:
                return

        # check whether the directory exists, create it if not
        dir_name = os.path.dirname(filename)
        if not os.path.exists(dir_name):
            os.mkdir(dir_name)

        # create config
        config = configparser.ConfigParser(allow_no_value=True)
        config.optionxform = str

        config["General settings"] = {}
        config["General settings"]["number of boards"] = str(self.num_boards)
        config["General settings"]["number of instructions"] = str(self.table.num_cols-len(self.table.horizontal_headers_init))
        config["General settings"][f"# from channel {num_ch_per_board-1} to channel 0"] = None
        for i in range(self.num_boards):
            config["General settings"][f"board {i} connections"] = ", ".join(self.table.compile_note_col()[i*num_ch_per_board:(i+1)*num_ch_per_board][::-1])

        instr_list = self.table.compile_instr()
        for j, instr in enumerate(instr_list[0]):
            config[f"Instr {j}"] = {}
            config[f"Instr {j}"]["instr note"] = instr[0]
            for i in range(self.num_boards):
                ttl = instr_list[i][j][1]
                config[f"Instr {j}"][f"board {i} ttl output pattern"] = '0b' + str(bin(ttl))[2:].zfill(num_ch_per_board)
            config[f"Instr {j}"]["op code"] = op_codes[instr[2]]
            config[f"Instr {j}"]["op data"] = str(instr[3])
            config[f"Instr {j}"]["duration time"] = str(instr[5])
            config[f"Instr {j}"]["duration unit"] = duration_units[instr[6]]

        config["Scanner settings"] = {}
        config["Scanner settings"]["sample number"] = str(self.scan_box.samp_num_sb.value())
        config["Scanner settings"]["repetition number"] = str(self.scan_box.rep_num_sb.value())
        config["Scanner settings"]["number of scan instr"] = str(self.scan_box.table.num_cols)
        config["Scanner settings"]["randomize sequence"] = str(self.scan_box.random_chb.isChecked())
        config["Scanner settings"]["DAQ DI channel"] = self.scan_box.daq_ch_le.text()

        scan_instr_list = self.scan_box.table.compile_scan_instr()
        for i, scan_instr in enumerate(scan_instr_list):
            config[f"Scan Instr {i}"] = scan_instr

        configfile = open(filename, "w")
        config.write(configfile)
        configfile.close()

    # load parameters from a local configuration file
    def load_config(self):
        filename, _ = qt.QFileDialog.getOpenFileName(self, "Load configs", "saved_configs/", "All Files (*);;INI File (*.ini)")
        if not filename:
            return

        config = configparser.ConfigParser()
        config.optionxform = str
        config.read(filename)

        self.table.load_config(config)
        self.scan_box.load_config(config)

    # Re-difine closeEvent. Ask before closing if the program is scanning
    def closeEvent(self, event):
        if not self.scan_box.scanning:
            super().closeEvent(event)

        else:
            # ask if continue to close
            ans = qt.QMessageBox.warning(self, 'Program warning',
                                'Warning: the program is scanning. Conitnue to close the program?',
                                qt.QMessageBox.Yes | qt.QMessageBox.No,
                                qt.QMessageBox.No)
            if ans == qt.QMessageBox.Yes:
                super().closeEvent(event)
            else:
                event.ignore()


if __name__ == '__main__':
    app = qt.QApplication(sys.argv)
    # screen = app.screens()
    # monitor_dpi = screen[0].physicalDotsPerInch()
    monitor_dpi = 96
    app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
    
    prog = mainWindow(app)
    app.exec_()

    # pb_close function has to be called at the end of any programming/start/stop instructions
    pb_close()

    sys.exit()