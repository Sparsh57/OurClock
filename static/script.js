// Global objects to store selected files, preview data, and column mappings
const selectedFiles = {
    courses: null,
    faculty: null,
    students: null
  };
  
  const previewData = {
    courses: [],
    faculty: [],
    students: []
  };
  
  const columnMappings = {
    courses_file: {},
    faculty_preferences_file: {},
    student_courses_file: {}
  };
  
  // Make variables globally accessible
  window.selectedFiles = selectedFiles;
  window.previewData = window.previewData || previewData;
  window.columnMappings = window.columnMappings || columnMappings;

  // Function to sync local data with global window objects
  function syncToGlobal() {
    window.selectedFiles = selectedFiles;
    Object.assign(window.previewData, previewData);
    Object.assign(window.columnMappings, columnMappings);
  }

  // Initialize LoadingManager
  let loadingManager;
  
  // Initialize when DOM is ready
  document.addEventListener('DOMContentLoaded', function() {
    // Use the global loadingManager instance created by loading.js
    if (window.loadingManager) {
      loadingManager = window.loadingManager;
    }
  });
  
  /**
   * Uploads a file for preview and renders the preview and mapping UI.
   * @param {string} fileType - "courses", "faculty", or "students"
   */
    async function previewFile(fileType) {
    const inputElem = document.getElementById(fileType + "Input");
    const file = inputElem.files[0];
    const errorElem = document.getElementById(fileType + "Error");
    const headerElem = document.getElementById(fileType + "Header");
    const bodyElem = document.getElementById(fileType + "Body");
    const mappingElem = document.getElementById(fileType + "Mapping");

    // Reset previous messages and table content
    errorElem.innerText = "";
    headerElem.innerHTML = "";
    bodyElem.innerHTML = "";
    mappingElem.innerHTML = "";

    if (!file) {
      errorElem.innerText = "No file selected.";
      return;
    }

    // Save file for final submission
    selectedFiles[fileType] = file;

    // Show loading screen for preview
    if (loadingManager) {
      loadingManager.showDataUpload();
    }

    let formData = new FormData();
    formData.append("file", file);
    formData.append("file_type", fileType);

    try {
      const response = await fetch("/upload/", {
        method: "POST",
        body: formData
      });
      const data = await response.json();

      if (data.error) {
        errorElem.innerText = data.error;
        return;
      }

      // Save raw preview data for this file type (UPDATE BOTH LOCAL AND GLOBAL)
      previewData[fileType] = data.preview || [];
        window.previewData[fileType] = data.preview || [];

      // Sync to global objects
      syncToGlobal();

      // Render preview table
      renderTable(fileType, data.preview || []);

      // Render mapping UI (if extra or missing columns exist)
      renderMappingUI(fileType, data.extra_cols || [], data.missing_cols || []);
    } catch (err) {
      console.error(`Preview error for ${fileType}:`, err);
      errorElem.innerText = "Preview failed. Check console.";
    } finally {
      // Hide loading screen
      if (loadingManager) {
        loadingManager.hide();
      }
    }
  }
  
  /**
   * Renders the preview table.
   */
  function renderTable(fileType, rows) {
  const headerElem = document.getElementById(fileType + "Header");
  const bodyElem   = document.getElementById(fileType + "Body");

  headerElem.innerHTML = "";
  bodyElem.innerHTML   = "";

  if (!rows.length) return;

  // Find the enclosing <table> and set collapse
  const table = headerElem.closest("table");
  if (table) {
    table.style.borderCollapse = "collapse";
    table.style.width         = "100%";
  }

  const columns = Object.keys(rows[0]);

  // HEADER
  columns.forEach(col => {
    const th = document.createElement("th");
    th.innerText = col;
    // inline border & padding
    th.style.border   = "1px solid #ccc";
    th.style.padding  = "8px 12px";
    th.style.textAlign= "left";
    headerElem.appendChild(th);
  });

  // BODY
  rows.forEach(row => {
    const tr = document.createElement("tr");

    columns.forEach(col => {
      const td = document.createElement("td");
      td.innerText = row[col];
      td.style.border  = "1px solid #ccc";
      td.style.padding = "8px 12px";
      tr.appendChild(td);
    });

    bodyElem.appendChild(tr);
  });
}

  
  /**
   * Renders dropdowns for mapping extra columns and displays missing columns.
   */
  function renderMappingUI(fileType, extraCols, missingCols) {
    const mappingElem = document.getElementById(fileType + "Mapping");
    mappingElem.innerHTML = '';
  
    // Map fileType to key used for final submission
    const keyMap = {
      courses: "courses_file",
      faculty: "faculty_preferences_file",
      students: "student_courses_file"
    };
    const fileKey = keyMap[fileType];
  
    // Reset mapping for this file
    columnMappings[fileKey] = {};
  
    // Display missing columns
    if (missingCols.length) {
      const p = document.createElement('p');
      p.textContent = 'Missing columns: ' + missingCols.join(', ');
      mappingElem.appendChild(p);
    }
  
    // If extra columns exist, build mapping controls
    if (extraCols.length) {
      const info = document.createElement('p');
      info.textContent = 'Map these extra columns to expected names:';
      mappingElem.appendChild(info);
  
      // Expected column lists
      const expectedMap = {
        courses: ["Course code", "Faculty Name", "Type", "Classes Per Week", "Number of Sections"],
        faculty: ["Name", "Busy Slot"],
        students: ["Roll No.", "G CODE", "Sections"]
      };
  
      extraCols.forEach(col => {
        const label = document.createElement('label');
        label.textContent = `"${col}" → `;
        const select = document.createElement('select');
        select.classList.add('browser-default');
        select.dataset.originalCol = col;  // store original name
  
        const emptyOpt = document.createElement('option');
        emptyOpt.value = '';
        emptyOpt.textContent = '-- select column --';
        select.appendChild(emptyOpt);
  
        expectedMap[fileType].forEach(expected => {
          const opt = document.createElement('option');
          opt.value = expected;
          opt.textContent = expected;
          select.appendChild(opt);
        });
  
        mappingElem.appendChild(label);
        mappingElem.appendChild(select);
        mappingElem.appendChild(document.createElement('br'));
      });
  
      // Confirm button
      const btn = document.createElement('button');
      btn.classList.add('btn');
      btn.textContent = `Apply mapping for ${fileType}`;
      btn.addEventListener('click', () => confirmMapping(fileType));
      mappingElem.appendChild(btn);
    } else if (!missingCols.length) {
      mappingElem.textContent = 'All columns match expected names.';
    }
  }
  
  /**
   * On "Confirm Mapping", this function:
   * - Reads dropdown selections,
   * - Renames the local preview data,
   * - Stores the mapping in the global columnMappings.
   */
    function confirmMapping(fileType, extraCols) {
    const keyMap = {
      courses: "courses_file",
      faculty: "faculty_preferences_file",
      students: "student_courses_file"
    };
    const fileKey = keyMap[fileType];

    let mapping = {};
    extraCols.forEach(col => {
      const select = document.getElementById(fileType + "_" + col);
      if (select && select.value) {
        mapping[col.trim()] = select.value.trim();
      }
    });
    
    // Update both local and global column mappings
    columnMappings[fileKey] = mapping;
    if (!window.columnMappings) {
      window.columnMappings = {
        courses_file: {},
        faculty_preferences_file: {},
        student_courses_file: {}
      };
    }
      window.columnMappings[fileKey] = mapping;

    // Rename keys in local previewData and update table for visual feedback.
    let newPreview = previewData[fileType].map(row => {
      let newRow = {};
      for (let key in row) {
        // If a mapping exists for the column (using trimmed keys)
        if (mapping[key.trim()]) {
          newRow[mapping[key.trim()]] = row[key];
        } else {
          newRow[key] = row[key];
        }
      }
      return newRow;
    });
    
    // Update both local and global preview data
    previewData[fileType] = newPreview;
    if (!window.previewData) {
      window.previewData = {
        courses: [],
        faculty: [],
        students: []
      };
    }
      window.previewData[fileType] = newPreview;

    // Sync to global objects
    syncToGlobal();

    // Re-render preview table with updated column names.
    renderTable(fileType, newPreview);

    alert(`Mapping for ${fileType} applied locally!`);
  }
  
  /**
   * Force show loading overlay directly (bypass LoadingManager issues)
   */
  function forceShowLoadingOverlay() {
    
    let overlay = document.getElementById('loading-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'loading-overlay';
      document.body.appendChild(overlay);
    }
    
    // Set content directly
    overlay.innerHTML = `
      <div style="
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(26, 35, 126, 0.9);
        z-index: 99999;
        display: flex;
        align-items: center;
        justify-content: center;
        font-family: Arial, sans-serif;
      ">
        <div style="
          background: white;
          padding: 40px;
          border-radius: 12px;
          text-align: center;
          max-width: 400px;
          min-width: 300px;
          box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        ">
          <div style="
            width: 40px;
            height: 40px;
            border: 4px solid #f3f3f3;
            border-top: 4px solid #2196F3;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 20px;
          "></div>
          <h5 style="color: #333; margin: 0 0 10px 0; font-size: 1.5rem; font-weight: 600;">Generating Timetable</h5>
          <p id="loading-message" style="color: #666; margin: 0 0 10px 0; font-size: 1rem;">Initializing timetable generation process...</p>
          <small id="loading-time" style="color: #999; font-size: 0.8rem;">Elapsed: 0s</small>
        </div>
      </div>
      <style>
        @keyframes spin {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
      </style>
    `;
    
    // Force display
    overlay.style.cssText = `
      position: fixed !important;
      top: 0 !important;
      left: 0 !important;
      width: 100% !important;
      height: 100% !important;
      z-index: 99999 !important;
      display: block !important;
    `;
    
    return overlay;
  }

  /**
   * Force hide loading overlay directly
   */
  function forceHideLoadingOverlay() {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) {
      overlay.style.display = 'none';
      overlay.remove();

    }
  }

  /**
   * Ensure loading overlay element exists and is properly set up
   */
  function ensureLoadingOverlay() {
    let overlay = document.getElementById('loading-overlay');
    
    if (!overlay) {

      overlay = document.createElement('div');
      overlay.id = 'loading-overlay';
      document.body.appendChild(overlay);
    }
    
    return overlay;
  }

  /**
   * Ensure DOM is ready and loading functionality is available
   */
  function ensureLoadingReady() {
    return new Promise((resolve) => {
      // Check if DOM is ready
      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
          setTimeout(resolve, 100); // Small delay to ensure scripts are loaded
        });
      } else {
        setTimeout(resolve, 100); // Small delay to ensure scripts are loaded
      }
    });
  }

  /**
   * Submits all three files and the column mappings to /send_admin_data.
   * Uses async task processing to avoid timeout issues.
   */
  async function submitAll() {
    // Ensure DOM and loading functionality is ready
    await ensureLoadingReady();
    
    const validationDiv = document.getElementById("submitValidation");
    if (!validationDiv) {
      console.error("submitValidation element not found!");
      return;
    }
    validationDiv.innerText = ""; // Clear previous errors
    
    // Validate files are selected
    if (!selectedFiles.courses || !selectedFiles.faculty || !selectedFiles.students) {
      const missingFiles = [];
      if (!selectedFiles.courses) missingFiles.push("Courses file");
      if (!selectedFiles.faculty) missingFiles.push("Faculty preferences file");
      if (!selectedFiles.students) missingFiles.push("Student courses file");
      
      validationDiv.innerText = `Missing: ${missingFiles.join(", ")}. Please preview all files first.`;
      alert("Please preview all three files before submitting.");
        return;
    }

    // Validate preview data exists and has content
    if (!previewData.courses || previewData.courses.length === 0) {
      validationDiv.innerText = "Courses file has no data. Please upload a file with valid course data.";
      alert("Courses file has no data. Please upload a file with valid course data.");
      return;
    }
    
    if (!previewData.faculty || previewData.faculty.length === 0) {
      validationDiv.innerText = "Faculty preferences file has no data. Please upload a file with valid faculty data.";
      alert("Faculty preferences file has no data. Please upload a file with valid faculty data.");
      return;
    }
    
    if (!previewData.students || previewData.students.length === 0) {
      validationDiv.innerText = "Student courses file has no data. Please upload a file with valid student enrollment data.";
      alert("Student courses file has no data. Please upload a file with valid student enrollment data.");
      return;
    }

    // Show loading screen for timetable generation
    ensureLoadingOverlay();
    
    // Check if loadingManager exists and is properly initialized
    if (typeof window.loadingManager !== 'undefined' && window.loadingManager) {
      try {
        // Check if overlay is empty and force create content if needed
        const overlay = document.getElementById('loading-overlay');
        
        if (overlay && overlay.childElementCount === 0) {
          if (typeof window.loadingManager.forceCreateContent === 'function') {
            window.loadingManager.forceCreateContent();
          } else {
            const htmlContent = `
              <div class="loading-container">
                <div class="loading-spinner">
                  <div class="custom-spinner"></div>
                </div>
                <div class="loading-content">
                  <h5 id="loading-title">Processing...</h5>
                  <p id="loading-message">Please wait while we process your request.</p>
                  <small id="loading-time">Elapsed: 0s</small>
                </div>
              </div>
            `;
            overlay.innerHTML = htmlContent;
          }
        }
        
        // Small delay to ensure content is rendered before showing
        setTimeout(() => {
          window.loadingManager.showTimetableGeneration();
          
          // Double-check if overlay is visible after calling show
          setTimeout(() => {
            const overlayAfterShow = document.getElementById('loading-overlay');
            
            // Check if overlay is actually visible, if not use direct approach
            const isVisible = overlayAfterShow && (
              overlayAfterShow.classList.contains('show') || 
              getComputedStyle(overlayAfterShow).display !== 'none'
            );
            
            if (!isVisible) {
              forceShowLoadingOverlay(); // Re-enabled as backup
            }
          }, 100);
        }, 50);
      } catch (error) {
        showSimpleLoading(); // Fallback
      }
    } else {
      showSimpleLoading(); // Fallback
    }

    let formData = new FormData();
    formData.append("courses_file", selectedFiles.courses);
    formData.append("faculty_preferences_file", selectedFiles.faculty);
    formData.append("student_courses_file", selectedFiles.students);
    formData.append("column_mappings", JSON.stringify(columnMappings));

    // Append the constraint toggles
    formData.append("toggle_prof",    document.getElementById("toggle_prof").checked);
    formData.append("toggle_capacity",document.getElementById("toggle_capacity").checked);
    formData.append("toggle_student", document.getElementById("toggle_student").checked);
    formData.append("toggle_same_day",document.getElementById("toggle_same_day").checked);
    formData.append("toggle_consec_days", document.getElementById("toggle_consec_days").checked);

    try {
      // Step 1: Submit files and start async task
      const response = await fetch("/send_admin_data", {
        method: "POST",
        body: formData
      });
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      
      const taskData = await response.json();
      const taskId = taskData.task_id;
      
      // Step 2: Poll for task completion
      await pollTaskStatus(taskId);
      
    } catch (err) {
      console.error("Submission error:", err);
      
      // Hide loading screen
      if (typeof window.loadingManager !== 'undefined' && window.loadingManager) {
        window.loadingManager.hide();
      } else {
        hideSimpleLoading();
      }
      
      // Also try direct hide as fallback
      setTimeout(() => {
        forceHideLoadingOverlay();
      }, 100);
      
      let errorMessage = "Submission failed: " + err.message;
      
      // Try to parse error response if it's JSON
      if (err.message.includes("HTTP")) {
        try {
          const errorResponse = await err.response.json();
          errorMessage = errorResponse.detail || errorMessage;
        } catch (parseError) {
          // Keep original error message
        }
      }
      
      validationDiv.innerText = errorMessage;
      alert(errorMessage);
    }
  }

  /**
   * Poll the server for task status until completion
   */
  async function pollTaskStatus(taskId) {
    const pollInterval = 2000; // Poll every 2 seconds
    const maxPolls = 900; // Maximum 30 minutes (900 * 2 seconds)
    let pollCount = 0;
    
    return new Promise((resolve, reject) => {
      const poll = async () => {
        try {
          pollCount++;
          
          if (pollCount > maxPolls) {
            reject(new Error("Task polling timeout - please check if the task completed successfully"));
            return;
          }
          
          const statusResponse = await fetch(`/task_status/${taskId}`);
          
          if (!statusResponse.ok) {
            reject(new Error(`Failed to get task status: ${statusResponse.statusText}`));
            return;
          }
          
          const status = await statusResponse.json();
          
          // Update loading message if possible
          if (typeof window.loadingManager !== 'undefined' && window.loadingManager && status.progress) {
            // Check and recreate overlay if needed
            window.loadingManager.checkAndRecreateOverlay();
            
            const messageElement = document.getElementById('loading-message');
            if (messageElement) {
              messageElement.textContent = status.progress;
            }
          } else if (status.progress) {
            // Update simple loading message
            const messageElement = document.getElementById('loading-message');
            if (messageElement) {
              messageElement.textContent = status.progress;
            }
          }
          
          if (status.status === "completed") {
            // Hide loading screen
            if (typeof window.loadingManager !== 'undefined' && window.loadingManager) {
              window.loadingManager.hide();
            } else {
              hideSimpleLoading();
            }
            
            // Also try direct hide as fallback
            setTimeout(() => {
              forceHideLoadingOverlay();
            }, 100);
            
            // Redirect to timetable page
            window.location.href = '/timetable';
            resolve();
            
          } else if (status.status === "failed") {
            // Hide loading screen
            if (typeof window.loadingManager !== 'undefined' && window.loadingManager) {
              window.loadingManager.hide();
            } else {
              hideSimpleLoading();
            }
            
            // Also try direct hide as fallback
            setTimeout(() => {
              forceHideLoadingOverlay();
            }, 100);
            
            const errorMessage = status.error || "Timetable generation failed";
            document.getElementById("submitValidation").innerText = errorMessage;
            alert("Error: " + errorMessage);
            reject(new Error(errorMessage));
            
          } else {
            // Still processing, continue polling
            setTimeout(poll, pollInterval);
          }
          
        } catch (error) {
          reject(error);
        }
      };
      
      // Start polling
      poll();
    });
  }

  // Simple loading screen functions
  function showSimpleLoading() {
    try {
      
      // Remove any existing loading overlay
      const existingOverlay = document.getElementById('simple-loading-overlay');
      if (existingOverlay) {
        existingOverlay.remove();
      }

      // Create a very simple loading overlay
      const overlay = document.createElement('div');
      overlay.id = 'simple-loading-overlay';
      overlay.style.cssText = `
        position: fixed !important;
        top: 0 !important;
        left: 0 !important;
        width: 100vw !important;
        height: 100vh !important;
        background: rgba(0, 0, 0, 0.8) !important;
        z-index: 99999 !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        color: white !important;
        font-family: Arial, sans-serif !important;
      `;
      
      overlay.innerHTML = `
        <div style="text-align: center; background: white; color: black; padding: 30px; border-radius: 10px; max-width: 400px; margin: 20px;">
          <div style="width: 30px; height: 30px; border: 3px solid #f3f3f3; border-top: 3px solid #3498db; border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto 20px;"></div>
          <h3 style="margin: 0 0 10px 0; font-size: 1.5rem;">Generating Timetable</h3>
          <p id="loading-message" style="margin: 0; font-size: 1rem;">Starting process...</p>
        </div>
        <style>
          @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
          }
        </style>
      `;
      
      // Safely append to body
      if (document.body) {
        document.body.appendChild(overlay);
      }
      
      // Force a reflow to ensure the element is rendered
      overlay.offsetHeight;
      
    } catch (error) {
      // Fallback: at least show an alert
      alert("Processing your request, please wait...");
    }
  }

  function hideSimpleLoading() {
    try {
      const overlay = document.getElementById('simple-loading-overlay');
      if (overlay) {
        overlay.remove();
      }
    } catch (error) {
      // Silently handle error
    }
  }
