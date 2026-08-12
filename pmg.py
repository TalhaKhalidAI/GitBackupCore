# auto_postman.py - COMPLETE DYNAMIC GENERATOR

import requests
import json
from typing import Dict, Any, Optional
import os
from datetime import datetime

class PostmanGenerator:
    """Auto-generate complete Postman collection from FastAPI"""
    
    def __init__(self, base_url: str = "http://localhost:2026"):
        self.base_url = base_url
        self.collection = {
            "info": {
                "name": f"API Collection - {datetime.now().strftime('%Y-%m-%d')}",
                "description": "Auto-generated from FastAPI OpenAPI spec",
                "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
            },
            "item": [],
            "variable": [
                {"key": "base_url", "value": base_url, "type": "string"},
                {"key": "access_token", "value": "", "type": "string"},
                {"key": "refresh_token", "value": "", "type": "string"}
            ]
        }
        self.folders = {}
        self.auth_endpoints = []
    
    def fetch_openapi(self) -> Dict:
        """Fetch OpenAPI spec from running server"""
        try:
            response = requests.get(f"{self.base_url}/openapi.json", timeout=5)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError:
            print(f"❌ Server not running at {self.base_url}")
            print("   Start with: uvicorn main:app --reload --host 0.0.0.0 --port 2026")
            raise
        except Exception as e:
            print(f"❌ Error fetching OpenAPI: {e}")
            raise
    
    def generate(self):
        """Generate complete Postman collection"""
        
        print(f"🔍 Fetching OpenAPI from {self.base_url}...")
        spec = self.fetch_openapi()
        
        # Add authentication workflow
        self._add_auth_workflow()
        
        # Process all paths
        total_endpoints = 0
        for path, path_item in spec.get("paths", {}).items():
            for method, operation in path_item.items():
                if method.lower() not in ["get", "post", "put", "delete", "patch", "options", "head"]:
                    continue
                
                # Create request item
                item = self._create_request_item(path, method, operation)
                
                # Add to folder based on tags
                tags = operation.get("tags", ["General"])
                folder_name = tags[0] if tags else "General"
                self._add_to_folder(item, folder_name)
                total_endpoints += 1
        
        # Add folder for auth endpoints
        self._add_auth_workflow()
        
        # Save collection
        output_file = "postman_collection.json"
        with open(output_file, "w") as f:
            json.dump(self.collection, f, indent=2)
        
        print(f"\n✅ Postman collection generated: {output_file}")
        print(f"📊 Total endpoints: {total_endpoints}")
        print(f"📁 Folders: {len(self.folders)}")
        
        return self.collection
    
    def _create_request_item(self, path: str, method: str, operation: Dict) -> Dict:
        """Create a complete Postman request item"""
        
        # Get summary and description
        summary = operation.get("summary", "")
        description = operation.get("description", "")
        operation_id = operation.get("operationId", f"{method}_{path.replace('/', '_')}")
        
        item = {
            "name": f"{method.upper()} {path}",
            "id": operation_id,
            "request": {
                "method": method.upper(),
                "header": [],
                "url": {
                    "raw": f"{{{{base_url}}}}{path}",
                    "host": ["{{base_url}}"],
                    "path": self._parse_path(path)
                },
                "description": summary or description
            },
            "response": []
        }
        
        # Check if endpoint requires authentication
        if operation.get("security") or self._requires_auth(path):
            item["request"]["header"].append({
                "key": "Authorization",
                "value": "Bearer {{access_token}}",
                "type": "text",
                "description": "Access token from login"
            })
            self.auth_endpoints.append(path)
        
        # Add query parameters
        query_params = self._get_query_params(operation)
        if query_params:
            item["request"]["url"]["query"] = query_params
        
        # Add request body for POST/PUT/PATCH
        if method.lower() in ["post", "put", "patch"]:
            body = self._get_request_body(operation)
            if body:
                item["request"]["body"] = body
                # Add Content-Type header if not present
                if not any(h.get("key") == "Content-Type" for h in item["request"]["header"]):
                    item["request"]["header"].append({
                        "key": "Content-Type",
                        "value": "application/json",
                        "type": "text"
                    })
        
        # Add test script for login endpoint
        if "/login" in path and method.lower() == "post":
            item["event"] = [
                {
                    "listen": "test",
                    "script": {
                        "exec": [
                            "// Auto-save token on successful login",
                            "if (pm.response.code === 200) {",
                            "    const jsonData = pm.response.json();",
                            "    if (jsonData.access_token) {",
                            "        pm.environment.set('access_token', jsonData.access_token);",
                            "        console.log('✅ Access token saved!');",
                            "    }",
                            "    if (jsonData.refresh_token) {",
                            "        pm.environment.set('refresh_token', jsonData.refresh_token);",
                            "        console.log('✅ Refresh token saved!');",
                            "    }",
                            "} else {",
                            "    console.log('❌ Login failed');",
                            "}"
                        ],
                        "type": "text/javascript"
                    }
                }
            ]
        
        # Add response examples
        responses = operation.get("responses", {})
        for status_code, response in responses.items():
            if status_code.startswith("2"):
                item["response"].append({
                    "name": f"Success {status_code}",
                    "status": status_code,
                    "code": int(status_code),
                    "body": self._get_response_example(response)
                })
        
        return item
    
    def _parse_path(self, path: str) -> list:
        """Parse path into segments"""
        if path == "/":
            return []
        return [segment for segment in path.strip("/").split("/") if segment]
    
    def _get_query_params(self, operation: Dict) -> list:
        """Extract query parameters from operation"""
        params = operation.get("parameters", [])
        query_params = []
        
        for param in params:
            if param.get("in") == "query":
                schema = param.get("schema", {})
                param_type = schema.get("type", "string")
                
                query_params.append({
                    "key": param["name"],
                    "value": schema.get("example", self._get_default_value(param_type)),
                    "description": param.get("description", ""),
                    "disabled": False
                })
        
        return query_params
    
    def _get_default_value(self, param_type: str) -> str:
        """Get default value based on type"""
        defaults = {
            "string": "string",
            "integer": "0",
            "number": "0.0",
            "boolean": "false",
            "array": "[]",
            "object": "{}"
        }
        return defaults.get(param_type, "string")
    
    def _get_request_body(self, operation: Dict) -> Optional[Dict]:
        """Extract request body schema and generate example"""
        
        request_body = operation.get("requestBody", {})
        if not request_body:
            return None
        
        content = request_body.get("content", {})
        
        # Check for JSON content
        if "application/json" in content:
            schema = content["application/json"].get("schema", {})
            example = self._generate_example_from_schema(schema)
            
            return {
                "mode": "raw",
                "raw": json.dumps(example, indent=2),
                "options": {
                    "raw": {
                        "language": "json"
                    }
                }
            }
        
        # Check for form data
        if "application/x-www-form-urlencoded" in content:
            schema = content["application/x-www-form-urlencoded"].get("schema", {})
            return {
                "mode": "urlencoded",
                "urlencoded": self._get_form_data(schema)
            }
        
        # Check for multipart form data
        if "multipart/form-data" in content:
            schema = content["multipart/form-data"].get("schema", {})
            return {
                "mode": "formdata",
                "formdata": self._get_form_data(schema)
            }
        
        return None
    
    def _generate_example_from_schema(self, schema: Dict) -> Dict:
        """Generate example from schema"""
        
        # If schema has example, use it
        if "example" in schema:
            return schema["example"]
        
        # If schema has properties, build example
        if "properties" in schema:
            example = {}
            for prop_name, prop_schema in schema["properties"].items():
                prop_type = prop_schema.get("type", "string")
                
                # Use examples if provided
                if "example" in prop_schema:
                    example[prop_name] = prop_schema["example"]
                elif prop_type == "string":
                    if "password" in prop_name.lower():
                        example[prop_name] = "Test@12345"
                    elif "email" in prop_name.lower():
                        example[prop_name] = "user@example.com"
                    elif "name" in prop_name.lower():
                        example[prop_name] = "John Doe"
                    else:
                        example[prop_name] = f"string_{prop_name}"
                elif prop_type == "integer":
                    example[prop_name] = 0
                elif prop_type == "number":
                    example[prop_name] = 0.0
                elif prop_type == "boolean":
                    example[prop_name] = False
                elif prop_type == "array":
                    example[prop_name] = []
                elif prop_type == "object":
                    example[prop_name] = {}
                else:
                    example[prop_name] = None
            
            # Add required fields first
            required = schema.get("required", [])
            if required:
                ordered_example = {}
                for field in required:
                    if field in example:
                        ordered_example[field] = example[field]
                for field, value in example.items():
                    if field not in ordered_example:
                        ordered_example[field] = value
                return ordered_example
            
            return example
        
        # If schema is a reference, try to resolve it
        if "$ref" in schema:
            # We could resolve references, but it's complex
            return {}
        
        # Fallback
        return {}
    
    def _get_form_data(self, schema: Dict) -> list:
        """Extract form data fields"""
        form_data = []
        properties = schema.get("properties", {})
        
        for prop_name, prop_schema in properties.items():
            form_data.append({
                "key": prop_name,
                "value": self._generate_example_from_schema(prop_schema),
                "type": "text",
                "enabled": True
            })
        
        return form_data
    
    def _get_response_example(self, response: Dict) -> Optional[str]:
        """Extract response example"""
        content = response.get("content", {})
        if "application/json" in content:
            schema = content["application/json"].get("schema", {})
            example = self._generate_example_from_schema(schema)
            if example:
                return json.dumps(example, indent=2)
        return None
    
    def _requires_auth(self, path: str) -> bool:
        """Check if endpoint requires authentication"""
        auth_paths = ["/me", "/profile", "/admin", "/users", "/logout"]
        return any(auth_path in path for auth_path in auth_paths)
    
    def _add_to_folder(self, item: Dict, folder_name: str):
        """Add item to a folder in the collection"""
        
        if folder_name not in self.folders:
            # Create folder
            folder = {
                "name": folder_name,
                "item": []
            }
            self.collection["item"].append(folder)
            self.folders[folder_name] = folder
        
        self.folders[folder_name]["item"].append(item)
    
    def _add_auth_workflow(self):
        """Add authentication workflow as first folder"""
        
        auth_folder = {
            "name": "🔐 Authentication",
            "item": [
                {
                    "name": "1. Login (Get Tokens)",
                    "request": {
                        "method": "POST",
                        "header": [
                            {"key": "Content-Type", "value": "application/json"}
                        ],
                        "body": {
                            "mode": "raw",
                            "raw": json.dumps({
                                "username": "talha",
                                "password": "Test@12345",
                                "use_cookie": False
                            }, indent=2),
                            "options": {"raw": {"language": "json"}}
                        },
                        "url": {
                            "raw": "{{base_url}}/app/v1/basic_auth/login",
                            "host": ["{{base_url}}"],
                            "path": ["app", "v1", "basic_auth", "login"]
                        }
                    },
                    "event": [
                        {
                            "listen": "test",
                            "script": {
                                "exec": [
                                    "if (pm.response.code === 200) {",
                                    "    const jsonData = pm.response.json();",
                                    "    pm.environment.set('access_token', jsonData.access_token);",
                                    "    pm.environment.set('refresh_token', jsonData.refresh_token);",
                                    "    console.log('✅ Tokens saved!');",
                                    "} else {",
                                    "    console.log('❌ Login failed');",
                                    "}"
                                ]
                            }
                        }
                    ]
                },
                {
                    "name": "2. Get Current User",
                    "request": {
                        "method": "GET",
                        "header": [
                            {"key": "Authorization", "value": "Bearer {{access_token}}"}
                        ],
                        "url": {
                            "raw": "{{base_url}}/app/v1/users/users_config/me",
                            "host": ["{{base_url}}"],
                            "path": ["app", "v1", "users", "users_config", "me"]
                        }
                    }
                },
                {
                    "name": "3. Logout",
                    "request": {
                        "method": "POST",
                        "header": [],
                        "url": {
                            "raw": "{{base_url}}/app/v1/basic_auth/logout",
                            "host": ["{{base_url}}"],
                            "path": ["app", "v1", "basic_auth", "logout"]
                        }
                    }
                }
            ]
        }
        
        # Insert at beginning
        self.collection["item"].insert(0, auth_folder)

# ========== RUN ==========
if __name__ == "__main__":
    import sys
    
    # Get base URL from command line or use default
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:2026"
    
    try:
        generator = PostmanGenerator(base_url)
        collection = generator.generate()
        
        print("\n" + "="*60)
        print("📥 HOW TO USE:")
        print("="*60)
        print("1. Open Postman")
        print("2. Click 'Import'")
        print("3. Select 'postman_collection.json'")
        print("4. Set environment variable: base_url = http://localhost:2026")
        print("5. Run '🔐 Authentication → 1. Login' to get token")
        print("6. All other endpoints will auto-use the token!")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nMake sure your server is running:")
        print("  uvicorn main:app --reload --host 0.0.0.0 --port 2026")