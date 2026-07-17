import fitz
import hashlib
import re
from typing import List, Dict, Any, Tuple
from collections import Counter

class DocumentParser:
    def __init__(self, file_path: str, version_name: str):
        self.file_path = file_path
        self.version_name = version_name
        self.doc = fitz.open(file_path)
        self.body_font_size = self._calculate_body_font_size()

    def _calculate_body_font_size(self) -> float:
        """
        Scans the document to find the most frequent font size, 
        which represents standard paragraph text.
        """
        sizes = []
        for page in self.doc:
            blocks = page.get_text("dict").get("blocks", [])
            for block in blocks:
                if block.get("type") == 0: # 0 means text block
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            text = span.get("text", "").strip()
                            if text:
                                sizes.append(round(span.get("size", 0), 1))
        
        if not sizes:
            return 11.0 # Safe fallback
            
        counter = Counter(sizes)
        # Return the most common font size
        return counter.most_common(1)[0][0]

    def _generate_node_id(self, index: int, heading: str) -> str:
        """
        Creates a deterministic ID. 
        Format: {version}_node_{index}_{sanitized_heading}
        This ensures duplicate headings get distinct, stable IDs.
        """
        clean_heading = re.sub(r'[^a-zA-Z0-9]+', '_', heading.strip())[:30]
        return f"{self.version_name}_node_{index}_{clean_heading}".strip('_')

    def _hash_content(self, heading: str, body: str) -> str:
        """
        Generates a SHA-256 hash of the node's textual content.
        Crucial for detecting staleness across document versions.
        """
        content = f"{heading.strip()}::{body.strip()}"
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def parse(self) -> List[Dict[str, Any]]:
        nodes = []
        
        # Stack tracks active headings: (node_id, font_size, level)
        # We push a dummy root node to handle top-level elements without errors
        stack: List[Tuple[str, float, int]] = [("root", 999.0, -1)]
        
        current_node = None
        node_counter = 0

        for page in self.doc:
            blocks = page.get_text("dict").get("blocks", [])
            for block in blocks:
                if block.get("type") != 0:
                    continue # Skip images/drawings for text hierarchy
                
                # Determine the primary font size of this block
                block_text = ""
                max_size = 0.0
                
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        block_text += span.get("text", "")
                        size = round(span.get("size", 0), 1)
                        if size > max_size:
                            max_size = size
                    block_text += "\n"
                
                block_text = block_text.strip()
                if not block_text:
                    continue

                # Is this block a heading?
                # Tolerance of 0.5 points accounts for minor PDF rendering artifacts
                if max_size > self.body_font_size + 0.5:
                    # Save the previous node before starting a new one
                    if current_node:
                        current_node["content_hash"] = self._hash_content(
                            current_node["heading"], current_node["body_text"]
                        )
                        nodes.append(current_node)

                    node_counter += 1
                    
                    # Pop stack until we find a parent with a larger font size
                    while len(stack) > 1 and stack[-1][1] <= max_size:
                        stack.pop()
                    
                    parent_id = stack[-1][0] if stack[-1][0] != "root" else None
                    level = stack[-1][2] + 1
                    
                    node_id = self._generate_node_id(node_counter, block_text)
                    
                    current_node = {
                        "id": node_id,
                        "parent_id": parent_id,
                        "level": level,
                        "heading": block_text,
                        "body_text": "",
                        "status": "new"
                    }
                    
                    # Push this new heading to the stack
                    stack.append((node_id, max_size, level))
                
                else:
                    # It's body text; append it to the current node
                    if current_node:
                        if current_node["body_text"]:
                            current_node["body_text"] += "\n"
                        current_node["body_text"] += block_text
                    else:
                        # Edge case: Body text appears before any heading
                        # Treat it as a Level 0 introductory node
                        node_counter += 1
                        node_id = self._generate_node_id(node_counter, "Introduction")
                        current_node = {
                            "id": node_id,
                            "parent_id": None,
                            "level": 0,
                            "heading": "Introduction",
                            "body_text": block_text,
                            "status": "new"
                        }
                        stack.append((node_id, max_size, 0))

        # Finalize the last node in the document
        if current_node:
            current_node["content_hash"] = self._hash_content(
                current_node["heading"], current_node["body_text"]
            )
            nodes.append(current_node)

        return nodes